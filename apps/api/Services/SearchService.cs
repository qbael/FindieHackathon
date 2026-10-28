using System.Text;
using System.Text.Json;
using Findie.Api.Contracts;
using Findie.Api.Infrastructure;
using Findie.Api.Models;
using Findie.Api.Repositories;
using Microsoft.AspNetCore.WebUtilities;
using Microsoft.Net.Http.Headers;

namespace Findie.Api.Services;

public interface ISearchService
{
    Task<SearchResponse> TextAsync(SearchRequest request, CancellationToken ct);
    Task<SearchResponse> ImageAsync(ImageSearchFilter filter, string? mime, Stream stream, long? length, CancellationToken ct);
    Task<SearchResponse> ImagesAsync(ImageSearchFilter filter, string? contentType, Stream stream, long? length, CancellationToken ct);
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
    public async Task<SearchResponse> ImagesAsync(ImageSearchFilter filter, string? contentType, Stream stream, long? length, CancellationToken ct)
    {
        ValidateFilters(filter.Area, filter.From, filter.Until, filter.Limit);
        if (length > 3 * BoundedImage.MaxBytes + 65536) throw new ApiException(413, "Search upload exceeds 30 MiB plus form headers.");
        if (!MediaTypeHeaderValue.TryParse(contentType, out var type) || type.MediaType != "multipart/form-data")
            throw new ApiException(415, "Use multipart/form-data with one to three images.");
        var boundary = HeaderUtilities.RemoveQuotes(type.Boundary).Value;
        if (string.IsNullOrWhiteSpace(boundary) || boundary.Length > 128) throw new ApiException(400, "Invalid multipart boundary.");
        var images = new List<(byte[] Bytes, string Mime)>();
        string? text = null;
        var hasText = false;
        try
        {
            try
            {
                var reader = new MultipartReader(boundary, stream) { HeadersCountLimit = 16, HeadersLengthLimit = 16384 };
                MultipartSection? section;
                while ((section = await reader.ReadNextSectionAsync(ct)) is not null)
                {
                    if (!ContentDispositionHeaderValue.TryParse(section.ContentDisposition, out var disposition)
                        || disposition.DispositionType != "form-data") throw new ApiException(400, "Invalid multipart field.");
                    var name = HeaderUtilities.RemoveQuotes(disposition.Name).Value;
                    var file = disposition.FileName.HasValue || disposition.FileNameStar.HasValue;
                    if (name == "images" && file)
                    {
                        if (images.Count == 3) throw new ApiException(400, "Upload at most three search images.");
                        if (!BoundedImage.Mime(section.ContentType)) throw new ApiException(415, "Use JPEG, PNG or WebP search images.");
                        images.Add((await BoundedImage.ReadAsync(section.Body, null, ct), section.ContentType!));
                    }
                    else if (name == "text" && !file && !hasText)
                    {
                        hasText = true;
                        var buffer = new byte[8001];
                        try
                        {
                            var used = 0;
                            int read;
                            while ((read = await section.Body.ReadAsync(buffer.AsMemory(used), ct)) > 0)
                            {
                                used += read;
                                if (used == buffer.Length) throw new ApiException(400, "Search text exceeds 2000 characters.");
                            }
                            text = RecoveryWorkflow.Optional(new UTF8Encoding(false, true).GetString(buffer, 0, used));
                            if (text?.Length > 2000) throw new ApiException(400, "Search text exceeds 2000 characters.");
                        }
                        finally { Array.Clear(buffer); }
                    }
                    else throw new ApiException(400, "Use only images and a single optional text field.");
                }
                if (images.Count == 0) throw new ApiException(400, "Upload one to three search images.");
            }
            catch (Exception error) when (error is IOException or InvalidDataException or DecoderFallbackException)
            { throw new ApiException(400, "Invalid multipart search input."); }
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
            timeout.CancelAfter(TimeSpan.FromSeconds(40));
            try
            {
                var rankings = new List<IReadOnlyList<SearchCandidate>>();
                foreach (var image in images)
                    rankings.Add(await QueryAsync("image", null, filter.Area, filter.From, filter.Until, filter.Limit,
                        image.Bytes, image.Mime, timeout.Token));
                if (text is not null)
                    rankings.Add(await QueryAsync("text", text, filter.Area, filter.From, filter.Until, filter.Limit,
                        [], "application/json", timeout.Token));
                return await ResultsAsync(rankings, text is null ? "image" : "combined",
                    text is null ? "image-fusion-v1" : "multimodal-fusion-v1", filter.Area, filter.From, filter.Until, filter.Limit, timeout.Token);
            }
            catch (OperationCanceledException) when (!ct.IsCancellationRequested)
            { throw new ApiException(503, "AI search timed out; use GET /api/items for basic filters."); }
        }
        finally { foreach (var image in images) Array.Clear(image.Bytes); }
    }
    async Task<SearchResponse> SearchAsync(string mode, string? text, string? area, DateOnly? from, DateOnly? until,
        int limit, byte[] bytes, string mime, CancellationToken ct) =>
        await ResultsAsync([await QueryAsync(mode, text, area, from, until, limit, bytes, mime, ct)], mode,
            AiProtocol.Setting(configuration, mode == "text" ? "TextSearchProfile" : "ImageSearchProfile"), area, from, until, limit, ct);

    async Task<IReadOnlyList<SearchCandidate>> QueryAsync(string mode, string? text, string? area, DateOnly? from, DateOnly? until,
        int limit, byte[] bytes, string mime, CancellationToken ct)
    {
        ValidateFilters(area, from, until, limit);
        area = RecoveryWorkflow.Optional(area);
        var model = AiProtocol.Setting(configuration, "EmbeddingModelId");
        var revision = AiProtocol.Setting(configuration, "EmbeddingRevision");
        var profile = AiProtocol.Setting(configuration, mode == "text" ? "TextSearchProfile" : "ImageSearchProfile");
        var metadata = JsonSerializer.SerializeToElement(new { schemaVersion = 1, modelId = model, modelRevision = revision,
            processingProfile = mode + "-v1", searchProfileId = profile, searchProfileVersion = 1,
            mode, area, from, until, limit, candidateLimit = 200, deadlineAt = DateTimeOffset.UtcNow.AddSeconds(30) }, RecoveryWorkflow.Json);
        var kind = mode == "image" ? "search.hybrid.image" : "search.hybrid";
        var body = mode == "image" ? bytes : JsonSerializer.SerializeToUtf8Bytes(new { text, area, from, until }, RecoveryWorkflow.Json);
        try
        {
            await using var reply = await ai.RequestAsync(new AiCommand(kind, metadata, body, mime), ct);
            AiProtocol.Require(reply.Metadata, kind);
            foreach (var field in new[] { "modelId", "modelRevision", "processingProfile", "searchProfileId", "searchProfileVersion" })
                if (reply.Metadata.GetProperty(field).ToString() != metadata.GetProperty(field).ToString()) throw new JsonException();
            if (reply.Body.Length > 262144) throw new JsonException();
            using var document = JsonDocument.Parse(reply.Body);
            var candidates = document.RootElement.GetProperty("candidates");
            if (candidates.ValueKind != JsonValueKind.Array || candidates.GetArrayLength() > 200) throw new JsonException();
            var result = new List<SearchCandidate>();
            foreach (var candidate in candidates.EnumerateArray())
            {
                result.Add(new SearchCandidate(candidate.GetProperty("itemId").GetGuid(), candidate.GetProperty("documentVersion").GetInt64(),
                    candidate.GetProperty("sourceId").GetGuid(), candidate.GetProperty("sourceVersion").GetInt64(),
                    candidate.GetProperty("sourceSha256").GetString(), mode == "image"));
            }
            await reply.CompleteAsync();
            return result;
        }
        catch (Exception error) when (AiProtocol.Malformed(error)) { throw new ApiException(502, "AI returned an invalid search response; use GET /api/items for basic filters."); }
        finally { if (mode == "text") Array.Clear(body); }
    }
    async Task<SearchResponse> ResultsAsync(IReadOnlyList<IReadOnlyList<SearchCandidate>> rankings, string mode, string profile,
        string? area, DateOnly? from, DateOnly? until, int limit, CancellationToken ct)
    {
        area = RecoveryWorkflow.Optional(area);
        var scores = new Dictionary<Guid, (double Score, Item Item)>();
        var items = new Dictionary<Guid, Item?>();
        var removed = false;
        foreach (var ranking in rankings)
        {
            var seen = new HashSet<Guid>();
            for (var rank = 0; rank < ranking.Count; rank++)
            {
                var candidate = ranking[rank];
                if (!items.TryGetValue(candidate.ItemId, out var item))
                    items[candidate.ItemId] = item = await repository.ItemAsync(candidate.ItemId, false, ct);
                var validSource = item is not null && (candidate.Image
                    ? item.Images.Any(image => image.Id == candidate.SourceId && RecoveryWorkflow.PublicImage(image)
                        && image.ContentVersion == candidate.SourceVersion && image.ProcessedObject!.Sha256 == candidate.SourceHash)
                    : candidate.SourceId == item.Id && item.ContentVersion == candidate.SourceVersion
                        && candidate.SourceHash == RecoveryWorkflow.Hash(item.Title + "\n" + item.PublicDescription));
                if (item is null || !RecoveryWorkflow.Public(item) || !validSource || !Matches(item, area, from, until)
                    || item.DocumentVersion != candidate.DocumentVersion || !seen.Add(candidate.ItemId))
                { removed = true; continue; }
                scores.TryGetValue(item.Id, out var current);
                scores[item.Id] = (current.Score + 1d / (61 + rank), item);
                if (rankings.Count == 1 && scores.Count == limit) break;
            }
        }
        var hits = scores.Values.OrderByDescending(value => value.Score).Take(limit)
            .Select((value, index) => new SearchHit(index + 1, RecoveryWorkflow.Response(value.Item))).ToList();
        return new SearchResponse(hits, mode, profile, 1, removed && hits.Count < limit, false, "/api/items");
    }
    static void ValidateFilters(string? area, DateOnly? from, DateOnly? until, int limit)
    {
        if (from > until || from == DateOnly.MinValue || until == DateOnly.MaxValue) throw new ApiException(400, "Invalid date filter.");
        if (area?.Length > 200 || limit is < 1 or > 10) throw new ApiException(400, "Invalid search filter.");
    }
    sealed record SearchCandidate(Guid ItemId, long DocumentVersion, Guid SourceId, long SourceVersion, string? SourceHash, bool Image);
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
