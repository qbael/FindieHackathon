using System.Text.Json;
using Findie.Api.Contracts;
using Findie.Api.Infrastructure;
using Findie.Api.Models;
using Findie.Api.Repositories;

namespace Findie.Api.Services;

public interface ISearchService
{
    Task<SearchResponse> TextAsync(SearchRequest request, CancellationToken ct);
    Task<SearchResponse> ImageAsync(ImageSearchFilter filter, string? mime, Stream stream, long? length, CancellationToken ct);
}

public sealed class SearchService(IRecoveryRepository repository, IAiGateway ai, IConfiguration configuration) : ISearchService
{
    public Task<SearchResponse> TextAsync(SearchRequest request, CancellationToken ct)
    {
        var text = RecoveryWorkflow.Text(request.Text, 2000, "Search text");
        return SearchAsync("text", text, request.Area, request.From, request.Until, request.Limit, [], "application/json", ct);
    }
    public async Task<SearchResponse> ImageAsync(ImageSearchFilter filter, string? mime, Stream stream, long? length, CancellationToken ct)
    {
        if (!BoundedImage.Mime(mime)) throw new ApiException(415, "Use a JPEG, PNG or WebP binary body.");
        var bytes = await BoundedImage.ReadAsync(stream, length, ct);
        try { return await SearchAsync("image", null, filter.Area, filter.From, filter.Until, filter.Limit, bytes, mime!, ct); }
        finally { Array.Clear(bytes); }
    }
    async Task<SearchResponse> SearchAsync(string mode, string? text, string? area, DateOnly? from, DateOnly? until,
        int limit, byte[] bytes, string mime, CancellationToken ct)
    {
        if (from > until || from == DateOnly.MinValue || until == DateOnly.MaxValue) throw new ApiException(400, "Invalid date filter.");
        area = RecoveryWorkflow.Optional(area);
        var model = AiProtocol.Setting(configuration, "EmbeddingModelId");
        var revision = AiProtocol.Setting(configuration, "EmbeddingRevision");
        var profile = AiProtocol.Setting(configuration, mode == "text" ? "TextSearchProfile" : "ImageSearchProfile");
        var metadata = JsonSerializer.SerializeToElement(new { schemaVersion = 1, modelId = model, modelRevision = revision,
            processingProfile = mode + "-v1", searchProfileId = profile, searchProfileVersion = 1,
            mode, area, from, until, limit, candidateLimit = 200, deadlineAt = DateTimeOffset.UtcNow.AddSeconds(30) }, RecoveryWorkflow.Json);
        var kind = mode == "image" ? "search.hybrid.image" : "search.hybrid";
        var body = mode == "image" ? bytes : JsonSerializer.SerializeToUtf8Bytes(new { text, area, from, until }, RecoveryWorkflow.Json);
        await using var reply = await ai.RequestAsync(new AiCommand(kind, metadata, body, mime), ct);
        try
        {
            AiProtocol.Require(reply.Metadata, kind);
            foreach (var field in new[] { "modelId", "modelRevision", "processingProfile", "searchProfileId", "searchProfileVersion" })
                if (reply.Metadata.GetProperty(field).ToString() != metadata.GetProperty(field).ToString()) throw new JsonException();
            if (reply.Body.Length > 262144) throw new JsonException();
            using var document = JsonDocument.Parse(reply.Body);
            var candidates = document.RootElement.GetProperty("candidates");
            if (candidates.ValueKind != JsonValueKind.Array || candidates.GetArrayLength() > 200) throw new JsonException();
            var hits = new List<SearchHit>();
            var seen = new HashSet<Guid>();
            var removed = false;
            foreach (var candidate in candidates.EnumerateArray())
            {
                var id = candidate.GetProperty("itemId").GetGuid();
                var item = await repository.ItemAsync(id, false, ct);
                var sourceId = candidate.GetProperty("sourceId").GetGuid();
                var sourceVersion = candidate.GetProperty("sourceVersion").GetInt64();
                var sourceHash = candidate.GetProperty("sourceSha256").GetString();
                var validSource = item is not null && (mode == "text"
                    ? sourceId == item.Id && item.ContentVersion == sourceVersion && sourceHash == RecoveryWorkflow.Hash(item.Title + "\n" + item.PublicDescription)
                    : item.Images.Any(image => image.Id == sourceId && RecoveryWorkflow.PublicImage(image)
                        && image.ContentVersion == sourceVersion && image.ProcessedObject!.Sha256 == sourceHash));
                if (item is null || !RecoveryWorkflow.Public(item) || !validSource || !Matches(item, area, from, until)
                    || item.DocumentVersion != candidate.GetProperty("documentVersion").GetInt64() || !seen.Add(id))
                { removed = true; continue; }
                hits.Add(new SearchHit(hits.Count + 1, RecoveryWorkflow.Response(item)));
                if (hits.Count == limit) break;
            }
            await reply.CompleteAsync();
            return new SearchResponse(hits, mode, profile, 1, removed && hits.Count < limit, false, "/api/items");
        }
        catch (Exception error) when (AiProtocol.Malformed(error)) { throw new ApiException(502, "AI returned an invalid search response; use GET /api/items for basic filters."); }
    }
    static bool Matches(Item item, string? area, DateOnly? from, DateOnly? until)
    {
        if (area is not null && !item.FoundArea.Contains(area, StringComparison.OrdinalIgnoreCase)) return false;
        if (from is { } first)
        {
            var start = new DateTimeOffset(first.ToDateTime(TimeOnly.MinValue), TimeSpan.FromHours(7)).ToUniversalTime();
            if (!(item.FoundOn >= first || (item.FoundUntil ?? item.FoundFrom) >= start)) return false;
        }
        if (until is { } last)
        {
            var end = new DateTimeOffset(last.AddDays(1).ToDateTime(TimeOnly.MinValue), TimeSpan.FromHours(7)).ToUniversalTime();
            if (!(item.FoundOn <= last || item.FoundFrom < end)) return false;
        }
        return true;
    }
}
