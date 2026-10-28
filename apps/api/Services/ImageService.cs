using System.Text.Json;
using Findie.Api.Contracts;
using Findie.Api.Infrastructure;
using Findie.Api.Models;
using Findie.Api.Repositories;

namespace Findie.Api.Services;

public interface IImageService
{
    Task<IReadOnlyList<ImageResponse>> ListAsync(Guid actor, Guid itemId, CancellationToken ct);
    Task<ImageResponse> UploadAsync(Guid actor, Guid key, Guid itemId, short position, string? mime, Stream body, long? length, CancellationToken ct);
    Task<ImageResponse> ReviewAsync(Guid actor, Guid key, Guid itemId, Guid imageId, ReviewImageRequest request, CancellationToken ct);
    Task<ImageResponse> RetireAsync(Guid actor, Guid key, Guid itemId, Guid imageId, RetireImageRequest request, CancellationToken ct);
    Task<(byte[] Bytes, string ContentType)> ContentAsync(Guid actor, Guid itemId, Guid imageId, CancellationToken ct);
}

public sealed class ImageService(IRecoveryRepository repository, RecoveryWorkflow workflow, IAiGateway ai,
    IProcessedStorage storage, IConfiguration configuration) : IImageService
{
    public async Task<IReadOnlyList<ImageResponse>> ListAsync(Guid actor, Guid itemId, CancellationToken ct)
    {
        var item = await workflow.ItemAsync(itemId, false, ct);
        await workflow.RequireManagerAsync(item, actor, ct);
        return item.Images.OrderBy(image => image.Position).ThenBy(image => image.CreatedAt).Select(Response).ToList();
    }
    public async Task<ImageResponse> UploadAsync(Guid actor, Guid key, Guid itemId, short position, string? mime,
        Stream body, long? length, CancellationToken ct)
    {
        var current = await workflow.ItemAsync(itemId, false, ct);
        await workflow.RequireManagerAsync(current, actor, ct);
        if (!BoundedImage.Mime(mime)) throw new ApiException(415, "Use image/jpeg, image/png or image/webp with a binary request body.");
        var bytes = await BoundedImage.ReadAsync(body, length, ct);
        try
        {
            var request = new { position, mime, sha256 = RecoveryWorkflow.Hash(bytes), length = bytes.Length };
            var operation = $"image.upload:{itemId}";
            if (await workflow.ReplayedAsync(actor, key, operation, request, "image", ct) is { } oldId)
                return Response(Find(current, oldId));
            RecoveryWorkflow.RequireActive(current);
            if (current.Images.Any(image => image.RetiredAt == null && image.Position == position))
                throw new ApiException(409, "This image position is occupied; retire the existing image first.");
            if (!storage.Configured) throw new ApiException(503, "Processed image storage is not configured.");
            var model = AiProtocol.Setting(configuration, "RedactionModelId");
            var revision = AiProtocol.Setting(configuration, "RedactionRevision");
            var profile = AiProtocol.Setting(configuration, "RedactionProfile");
            var imageId = Guid.NewGuid();
            var metadata = JsonSerializer.SerializeToElement(new { schemaVersion = 1, imageId, itemId, sourceVersion = 1,
                sourceSha256 = request.sha256, modelId = model, modelRevision = revision, processingProfile = profile,
                deadlineAt = DateTimeOffset.UtcNow.AddSeconds(30) }, RecoveryWorkflow.Json);
            await using var reply = await ai.RequestAsync(new AiCommand("image.redact", metadata, bytes, mime!), ct);
            var output = ValidateOutput(reply, metadata);
            var value = new StoredObject { OwnerUserId = actor, Bucket = storage.Bucket, ObjectKey = $"processed/{itemId}/{Guid.NewGuid():N}",
                Sha256 = output.Hash, ContentType = output.Mime, ByteSize = reply.Body.Length, Width = output.Width, Height = output.Height,
                ExpiresAt = DateTimeOffset.UtcNow.AddHours(1), CleanupNextAt = DateTimeOffset.UtcNow.AddHours(1) };
            repository.Add(value);
            await repository.SaveAsync(ct);
            await storage.PutAsync(value, reply.Body, ct);
            var id = await workflow.WriteAsync(actor, key, operation, request, "image", 201, async () =>
            {
                var item = await workflow.ItemAsync(itemId, true, ct);
                await workflow.RequireManagerAsync(item, actor, ct);
                RecoveryWorkflow.RequireActive(item);
                RecoveryWorkflow.RequireVersion(item, current.RowVersion);
                await repository.LockObjectAsync(value, ct);
                if (value.ObjectState != "reserved" || value.ExpiresAt <= DateTimeOffset.UtcNow)
                    throw new ApiException(409, "The output reservation expired; upload the image again.");
                if (item.Images.Any(image => image.RetiredAt == null && image.Position == position))
                    throw new ApiException(409, "This image position was occupied during processing.");
                value.ObjectState = "validated";
                value.ValidatedAt = DateTimeOffset.UtcNow;
                value.ExpiresAt = value.CleanupNextAt = null;
                var image = new ItemImage { Id = imageId, ItemId = itemId, Position = position, ProcessedObjectId = value.Id,
                    ProcessedObject = value, ProcessingState = "needs_review", SensitiveRegions = output.Regions,
                    RedactionModelId = model, RedactionModelRevision = revision, RedactionProfile = profile };
                repository.Add(image);
                item.Images.Add(image);
                workflow.Changed(item);
                return imageId;
            }, ct);
            await reply.CompleteAsync();
            return Response(Find(await workflow.ItemAsync(itemId, false, ct), id));
        }
        finally { Array.Clear(bytes); }
    }
    static (string Mime, string Hash, int Width, int Height, string Regions) ValidateOutput(AiReply reply, JsonElement expected)
    {
        try
        {
            var data = reply.Metadata;
            AiProtocol.Require(data, "image.redact");
            foreach (var field in new[] { "imageId", "itemId", "sourceVersion", "sourceSha256", "modelId", "modelRevision", "processingProfile" })
                if (data.GetProperty(field).ToString() != expected.GetProperty(field).ToString()) throw new JsonException();
            var mime = data.GetProperty("contentType").GetString()!;
            var hash = data.GetProperty("sha256").GetString()!;
            var width = data.GetProperty("width").GetInt32();
            var height = data.GetProperty("height").GetInt32();
            var regions = data.GetProperty("sensitiveRegions");
            if (!BoundedImage.Mime(mime) || !BoundedImage.Signature(reply.Body, mime) || reply.Body.Length > BoundedImage.MaxBytes
                || data.GetProperty("byteSize").GetInt32() != reply.Body.Length || hash != RecoveryWorkflow.Hash(reply.Body)
                || width is < 1 or > 10000 || height is < 1 or > 10000 || (long)width * height > 40000000
                || regions.ValueKind != JsonValueKind.Array || regions.GetRawText().Length > 8000) throw new JsonException();
            return (mime, hash, width, height, regions.GetRawText());
        }
        catch (Exception error) when (AiProtocol.Malformed(error)) { throw new ApiException(502, "AI returned an invalid processed image; no image was stored."); }
    }
    public async Task<ImageResponse> ReviewAsync(Guid actor, Guid key, Guid itemId, Guid imageId, ReviewImageRequest request, CancellationToken ct)
    {
        await workflow.WriteAsync(actor, key, $"image.review:{itemId}:{imageId}", request, "image", 200, async () =>
        {
            var item = await workflow.ItemAsync(itemId, true, ct);
            await workflow.RequireManagerAsync(item, actor, ct);
            RecoveryWorkflow.RequireActive(item);
            var image = Find(item, imageId);
            if (image.ContentVersion != request.ContentVersion || image.RetiredAt != null
                || image.ProcessingState is not ("needs_review" or "ready") || image.ProcessedObject?.ObjectState != "validated")
                throw new ApiException(409, "The output changed or is no longer reviewable.");
            image.ReviewState = request.Decision;
            image.ProcessingState = request.Decision == "approved" ? "ready" : "rejected";
            image.ReviewedBy = actor;
            image.ReviewedAt = DateTimeOffset.UtcNow;
            workflow.Changed(item);
            return imageId;
        }, ct);
        var current = await workflow.ItemAsync(itemId, false, ct);
        await workflow.RequireManagerAsync(current, actor, ct);
        return Response(Find(current, imageId));
    }
    public async Task<ImageResponse> RetireAsync(Guid actor, Guid key, Guid itemId, Guid imageId, RetireImageRequest request, CancellationToken ct)
    {
        await workflow.WriteAsync(actor, key, $"image.retire:{itemId}:{imageId}", request, "image", 200, async () =>
        {
            var item = await workflow.ItemAsync(itemId, true, ct);
            await workflow.RequireManagerAsync(item, actor, ct);
            var image = Find(item, imageId);
            if (image.ContentVersion != request.ContentVersion || image.RetiredAt is not null) throw new ApiException(409, "The image changed or was already retired.");
            image.RetiredAt = DateTimeOffset.UtcNow;
            image.ContentVersion++;
            if (image.ProcessedObject is { } value)
            {
                value.ObjectState = "delete_pending";
                value.CleanupNextAt = DateTimeOffset.UtcNow;
            }
            image.ProcessedObject = null;
            image.ProcessedObjectId = null;
            image.ProcessingState = "rejected";
            image.ReviewState = "rejected";
            image.ReviewedBy = actor;
            image.ReviewedAt = DateTimeOffset.UtcNow;
            workflow.Changed(item);
            return imageId;
        }, ct);
        var current = await workflow.ItemAsync(itemId, false, ct);
        await workflow.RequireManagerAsync(current, actor, ct);
        return Response(Find(current, imageId));
    }
    public async Task<(byte[] Bytes, string ContentType)> ContentAsync(Guid actor, Guid itemId, Guid imageId, CancellationToken ct)
    {
        var item = await workflow.ItemAsync(itemId, false, ct);
        var image = Find(item, imageId);
        if (image.RetiredAt != null || image.ProcessedObject is not { ObjectState: "validated", ObjectKind: "processed" } value
            || !(RecoveryWorkflow.Public(item) && RecoveryWorkflow.PublicImage(image)) && !await workflow.CanManageAsync(item, actor, ct))
            throw new ApiException(404, "Processed image not found.");
        var bytes = await storage.ReadAsync(value, ct);
        if (bytes.Length != value.ByteSize || RecoveryWorkflow.Hash(bytes) != value.Sha256)
            throw new ApiException(503, "The stored output failed integrity verification.");
        var latest = await workflow.ItemAsync(itemId, false, ct);
        var source = Find(latest, imageId);
        if (source.RetiredAt != null || source.ContentVersion != image.ContentVersion || source.ProcessedObjectId != value.Id
            || source.ProcessedObject?.ObjectState != "validated"
            || !(RecoveryWorkflow.Public(latest) && RecoveryWorkflow.PublicImage(source)) && !await workflow.CanManageAsync(latest, actor, ct))
        { Array.Clear(bytes); throw new ApiException(404, "Processed image is no longer available."); }
        return (bytes, value.ContentType!);
    }
    static ItemImage Find(Item item, Guid id) => item.Images.SingleOrDefault(image => image.Id == id) ?? throw new ApiException(404, "Image not found.");
    static ImageResponse Response(ItemImage image) => new(image.Id, image.ItemId, image.Position, image.ContentVersion,
        image.ProcessingState, image.ReviewState, image.FailureCode,
        image.RetiredAt == null && image.ProcessedObject is { ObjectState: "validated" } ? $"/api/items/{image.ItemId}/images/{image.Id}/content" : null);
}

public static class AiProtocol
{
    public static int EmbeddingDimensions(IConfiguration configuration) =>
        int.TryParse(configuration["Ai:EmbeddingDimensions"], out var dimensions) && dimensions is > 0 and <= 16000
            ? dimensions : throw new ApiException(503, "AI embedding dimensions must be configured between 1 and 16000.");
    public static bool Malformed(Exception error) => error is JsonException or KeyNotFoundException or InvalidOperationException or FormatException or OverflowException;
    public static void Require(JsonElement data, string kind)
    {
        if (data.GetProperty("schemaVersion").GetInt32() != 1 || data.GetProperty("kind").GetString() != kind) throw new JsonException();
        if (!data.GetProperty("succeeded").GetBoolean()) throw new ApiException(503, "AI processing failed; retry or use basic item filters.");
    }
    public static string Setting(IConfiguration configuration, string key) => configuration["Ai:" + key] is { Length: > 0 } value
        && value is not ("main" or "latest") ? value : throw new ApiException(503, "AI model revision/profile is not configured.");
}
