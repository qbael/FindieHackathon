using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using Findie.Api.Data;
using Findie.Api.Infrastructure;
using Findie.Api.Models;
using Findie.Api.Services;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;

static class ImageSearchChecks
{
    static int checks;
    static readonly byte[] Output = Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j8i0AAAAASUVORK5CYII=");
    public static async Task RunAsync(WebApplicationFactory<FindieDbContext> factory, StubAiGateway ai, StubStorage storage,
        Func<HttpClient, string, Task> login)
    {
        foreach (var value in new string?[] { null, "", "0", "-1", "16001", "not-a-number" })
        {
            var configuration = new ConfigurationBuilder().AddInMemoryCollection(
                new Dictionary<string, string?> { ["Ai:EmbeddingDimensions"] = value }).Build();
            try { AiProtocol.EmbeddingDimensions(configuration); throw new InvalidOperationException("Invalid embedding dimensions should fail."); }
            catch (ApiException error) when (error.StatusCode == 503) { Check(true, "invalid embedding dimensions are rejected"); }
        }
        using var owner = await User("image-owner");
        using var seeker = await User("image-seeker");
        var item = await Send(owner, HttpMethod.Post, "/api/items", Create("Image test"), 201);
        var itemId = item.GetProperty("id").GetGuid();
        await Send(owner, HttpMethod.Put, $"/api/items/{itemId}/publication", new { rowVersion = 1, state = "published" }, 409);
        var imagesPath = $"/api/items/{itemId}/images";
        var original = Encoding.UTF8.GetBytes("PRIVATE ORIGINAL INPUT - MUST NEVER ENTER STORAGE");
        byte[]? lastInput = null;
        await Binary(owner, imagesPath, original, "application/octet-stream", 415);
        await Binary(owner, imagesPath, [], "image/png", 400);
        await Binary(owner, imagesPath, new byte[BoundedImage.MaxBytes + 1], "image/png", 413);
        await Binary(seeker, imagesPath, original, "image/png", 403);
        await Binary(owner, imagesPath, original, "image/png", 503);
        Check(storage.Puts == 0, "AI failure never uploads original or output");
        ai.Handler = command =>
        {
            var metadata = ImageMetadata(command);
            metadata["sha256"] = new string('0', 64);
            return Task.FromResult(new AiReply(JsonSerializer.SerializeToElement(metadata), Output.ToArray()));
        };
        await Binary(owner, imagesPath, original, "image/png", 502);
        Check(storage.Puts == 0, "invalid output hash never reaches R2");
        ai.Handler = ImageReply;
        var uploadKey = Guid.NewGuid();
        var image = await Binary(owner, imagesPath, original, "image/png", 201, uploadKey);
        Check(lastInput?.All(value => value == 0) == true, "raw request buffer is cleared after processing");
        var imageId = image.GetProperty("id").GetGuid();
        var contentPath = $"{imagesPath}/{imageId}/content";
        var reviewPath = $"{imagesPath}/{imageId}/review";
        Check(image.GetProperty("processingState").GetString() == "needs_review", "output is held for human review");
        var calls = ai.Calls;
        var replay = await Binary(owner, imagesPath, original, "image/png", 201, uploadKey);
        Check(replay.GetProperty("id").GetGuid() == imageId && calls == ai.Calls && storage.Puts == 1, "upload replay avoids AI and R2 writes");
        await Binary(owner, imagesPath, original, "image/png", 409);
        await Send(seeker, HttpMethod.Get, imagesPath, null, 403);
        await Send(owner, HttpMethod.Get, imagesPath, null, 200);
        await Send(seeker, HttpMethod.Get, contentPath, null, 404);
        using (var content = await owner.GetAsync(contentPath))
        {
            Check(content.StatusCode == HttpStatusCode.OK && (await content.Content.ReadAsByteArrayAsync()).SequenceEqual(Output), "review preview contains only processed bytes");
            Check(content.Headers.CacheControl?.NoStore == true, "private output responses prohibit caching");
        }
        Check((await Get(owner, $"/api/items/{itemId}")).GetProperty("images").GetArrayLength() == 0, "pending output is excluded from the item DTO");
        await Send(seeker, HttpMethod.Get, $"/api/items/{itemId}", null, 404);
        item = await Get(owner, $"/api/items/{itemId}");
        await Send(owner, HttpMethod.Put, $"/api/items/{itemId}/publication", new { rowVersion = item.GetProperty("rowVersion").GetInt64(), state = "published" }, 409);
        await Send(seeker, HttpMethod.Post, reviewPath, new { contentVersion = 1, decision = "approved" }, 403);
        await Send(owner, HttpMethod.Post, reviewPath, new { contentVersion = 2, decision = "approved" }, 409);
        await Send(owner, HttpMethod.Post, reviewPath, new { contentVersion = 1, decision = "approved" }, 200);
        item = await Get(owner, $"/api/items/{itemId}");
        item = await Send(owner, HttpMethod.Put, $"/api/items/{itemId}/publication", new { rowVersion = item.GetProperty("rowVersion").GetInt64(), state = "published" }, 200);
        Check((await Get(seeker, $"/api/items/{itemId}")).GetProperty("images").GetArrayLength() == 1, "approved output becomes public");
        using (var content = await seeker.GetAsync(contentPath)) Check(content.IsSuccessStatusCode, "approved public output is readable");
        storage.CorruptRead = true;
        await Send(seeker, HttpMethod.Get, contentPath, null, 503);
        storage.CorruptRead = false;

        var returned = await Send(owner, HttpMethod.Post, "/api/items", new
        { content = Content("Upload replay after return"), custody = new { kind = "external", name = "Library", address = "Campus desk" } }, 201);
        var returnedId = returned.GetProperty("id").GetGuid();
        var returnedImages = $"/api/items/{returnedId}/images";
        var returnedUploadKey = Guid.NewGuid();
        var returnedImage = await Binary(owner, returnedImages, original, "image/png", 201, returnedUploadKey);
        await Send(owner, HttpMethod.Post, $"/api/items/{returnedId}/return", new { rowVersion = 2, confirmedPhysicalHandover = true }, 201);
        var callsAfterReturn = ai.Calls;
        var putsAfterReturn = storage.Puts;
        var returnedReplay = await Binary(owner, returnedImages, original, "image/png", 201, returnedUploadKey);
        Check(returnedReplay.GetProperty("id").GetGuid() == returnedImage.GetProperty("id").GetGuid()
            && ai.Calls == callsAfterReturn && storage.Puts == putsAfterReturn, "upload replay after handover returns the same image without calling AI or R2");
        await Binary(owner, returnedImages + "?position=2", original, "image/png", 409);
        await Send(owner, HttpMethod.Post, $"{returnedImages}/{returnedImage.GetProperty("id").GetGuid()}/retire", new { contentVersion = 1 }, 200);

        var otherItem = await Send(owner, HttpMethod.Post, "/api/items", Create("Other image test"), 201);
        var otherId = otherItem.GetProperty("id").GetGuid();
        await Send(owner, HttpMethod.Post, $"/api/items/{otherId}/images/{imageId}/review", new { contentVersion = 1, decision = "approved" }, 404);
        storage.FailPut = true;
        await Binary(owner, $"/api/items/{otherId}/images", original, "image/png", 503);
        storage.FailPut = false;
        Check((await Get(owner, $"/api/items/{otherId}/images")).GetArrayLength() == 0, "failed R2 upload leaves no attached image");
        var processing = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var resume = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        ai.Handler = async command => { processing.SetResult(); await resume.Task; return await ImageReply(command); };
        var inFlight = Binary(owner, $"/api/items/{otherId}/images", original, "image/png", 409);
        await processing.Task.WaitAsync(TimeSpan.FromSeconds(10));
        await Send(owner, HttpMethod.Put, $"/api/items/{otherId}", new { rowVersion = 1, content = Content("Edited while processing") }, 200);
        resume.SetResult();
        await inFlight;
        Check((await Get(owner, $"/api/items/{otherId}/images")).GetArrayLength() == 0, "late processing output cannot attach to a changed item");
        ai.Handler = ImageReply;

        var second = await Send(owner, HttpMethod.Post, "/api/items", Create("Second searchable item"), 201);
        await PublicationImageFixture.EnsureAsync(factory, second.GetProperty("id").GetGuid());
        second = await Send(owner, HttpMethod.Put, $"/api/items/{second.GetProperty("id").GetGuid()}/publication", new { rowVersion = 1, state = "published" }, 200);
        var secondId = second.GetProperty("id").GetGuid();
        var firstCandidate = await Candidate(itemId, false);
        var secondCandidate = await Candidate(secondId, false);
        await Send(seeker, HttpMethod.Post, "/api/search", new { text = "  " }, 400);
        await Send(seeker, HttpMethod.Post, "/api/search", new { text = "wallet", limit = 11 }, 400);
        await Send(seeker, HttpMethod.Post, "/api/search", new { text = "wallet", from = "2026-02-01", until = "2026-01-01" }, 400);
        await Send(seeker, HttpMethod.Post, "/api/search", new { text = "wallet", from = "0001-01-01" }, 400);
        ai.Handler = _ => throw new ApiException(503, "Worker unavailable.");
        await Send(seeker, HttpMethod.Post, "/api/search", new { text = "wallet" }, 503);
        ai.Handler = command => SearchReply(command, [secondCandidate, firstCandidate, secondCandidate]);
        var results = await Send(seeker, HttpMethod.Post, "/api/search", new { text = "ví màu đen", area = "Campus", from = "2026-01-01", until = "2026-01-01" }, 200);
        Check(results.GetProperty("items").GetArrayLength() == 2 && results.GetProperty("items")[0].GetProperty("item").GetProperty("id").GetGuid() == secondId,
            "search rehydrates eligible items, deduplicates and preserves worker ranking");
        await Send(owner, HttpMethod.Put, $"/api/items/{secondId}/publication", new { rowVersion = 2, state = "hidden" }, 200);
        results = await Send(seeker, HttpMethod.Post, "/api/search", new { text = "wallet" }, 200);
        Check(results.GetProperty("items").GetArrayLength() == 1 && results.GetProperty("partial").GetBoolean(), "hidden and stale candidates are removed at response time");
        results = await Send(seeker, HttpMethod.Post, "/api/search", new { text = "wallet", area = "Different district" }, 200);
        Check(results.GetProperty("items").GetArrayLength() == 0 && !results.GetProperty("filtersRelaxed").GetBoolean(), "business filters are rechecked without silently widening them");
        ai.Handler = command => SearchReply(command, []);
        results = await Send(seeker, HttpMethod.Post, "/api/search", new { text = "missing" }, 200);
        Check(results.GetProperty("items").GetArrayLength() == 0, "successful empty search differs from unavailable worker");
        ai.Handler = command => {
            var metadata = StubAiGateway.ReplyMetadata(command); metadata["modelRevision"] = "wrong-model";
            return Task.FromResult(new AiReply(JsonSerializer.SerializeToElement(metadata), "{\"candidates\":[]}"u8.ToArray()));
        };
        await Send(seeker, HttpMethod.Post, "/api/search", new { text = "wallet" }, 502);
        var imageCandidate = await Candidate(itemId, true);
        ai.Handler = command => {
            Check(command.Kind == "search.hybrid.image" && !command.Persistent && command.Body.SequenceEqual(original), "image query uses transient binary transport");
            return SearchReply(command, [imageCandidate]);
        };
        var putCount = storage.Puts;
        results = await Binary(seeker, "/api/search/image", original, "image/png", 200);
        Check(results.GetProperty("items").GetArrayLength() == 1 && storage.Puts == putCount, "image search never writes query images to R2");
        await CheckMultipartSearch();
        var reading = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var releaseRead = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        storage.OnRead = async () => { reading.SetResult(); await releaseRead.Task; };
        var staleRead = Send(seeker, HttpMethod.Get, contentPath, null, 404);
        await reading.Task.WaitAsync(TimeSpan.FromSeconds(10));
        await Send(owner, HttpMethod.Post, reviewPath, new { contentVersion = 1, decision = "rejected" }, 200);
        releaseRead.SetResult();
        await staleRead;
        storage.OnRead = null;
        await Send(seeker, HttpMethod.Get, contentPath, null, 404);
        item = await Get(owner, $"/api/items/{itemId}");
        Check(item.GetProperty("publicationState").GetString() == "hidden", "rejecting the last public image hides the item");
        await Send(owner, HttpMethod.Put, $"/api/items/{itemId}/publication", new { rowVersion = item.GetProperty("rowVersion").GetInt64(), state = "published" }, 409);
        results = await Binary(seeker, "/api/search/image", original, "image/png", 200);
        Check(results.GetProperty("items").GetArrayLength() == 0, "revoked image review invalidates old search sources");
        await Send(owner, HttpMethod.Post, $"{imagesPath}/{imageId}/retire", new { contentVersion = 1 }, 200);
        await Send(owner, HttpMethod.Get, contentPath, null, 404);
        ai.Handler = ImageReply;
        var replacement = await Binary(owner, imagesPath, original, "image/png", 201);
        var replacementId = replacement.GetProperty("id").GetGuid();
        await Send(owner, HttpMethod.Post, $"{imagesPath}/{replacementId}/review", new { contentVersion = 1, decision = "approved" }, 200);
        item = await Get(owner, $"/api/items/{itemId}");
        Check(item.GetProperty("publicationState").GetString() == "hidden", "approving a replacement does not automatically republish the item");
        item = await Send(owner, HttpMethod.Put, $"/api/items/{itemId}/publication", new { rowVersion = item.GetProperty("rowVersion").GetInt64(), state = "published" }, 200);
        await Send(owner, HttpMethod.Post, $"{imagesPath}/{replacementId}/retire", new { contentVersion = 1 }, 200);
        Check((await Get(owner, $"/api/items/{itemId}")).GetProperty("publicationState").GetString() == "hidden", "retiring the last public image hides the item");
        await Send(seeker, HttpMethod.Get, $"/api/items/{itemId}", null, 404);

        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
            Check((await db.StoredObjects.ToListAsync()).All(value => value.ObjectKind == "processed" && value.Sha256 != RecoveryWorkflow.Hash(original)), "database contains only processed output metadata");
            Check(storage.Objects.Values.All(value => value.SequenceEqual(Output)), "R2 receives only normalized output");
            Check((await db.IndexOutbox.Select(value => value.Payload).ToListAsync()).All(value => !value.Contains("PRIVATE ORIGINAL")), "raw input never enters outbox");
            await db.StoredObjects.Where(value => value.ObjectState == "reserved").ExecuteUpdateAsync(update => update
                .SetProperty(value => value.ExpiresAt, DateTimeOffset.UtcNow.AddSeconds(-1)));
        }
        var maintenance = new RecoveryMaintenance(factory.Services.GetRequiredService<IServiceScopeFactory>(), ai, storage,
            factory.Services.GetRequiredService<IConfiguration>(), NullLogger<RecoveryMaintenance>.Instance);
        while (await maintenance.CleanupOneAsync(default)) { }
        Check(storage.Objects.Count == 0, "retired and abandoned outputs are cleaned without original payloads");
        await CheckOutbox(maintenance);
        await CheckUploadLimit();
        Console.WriteLine($"PASS: {checks} image/search/outbox checks (output-only storage, review, stale results, bounded retry and cleanup)");

        async Task CheckUploadLimit()
        {
            using var browser = await User("image-limit-owner");
            var actor = (await Get(browser, "/api/users/me")).GetProperty("id").GetGuid();
            var limitedItem = await Send(browser, HttpMethod.Post, "/api/items", Create("Three image limit"), 201);
            var limitedId = limitedItem.GetProperty("id").GetGuid();
            var path = $"/api/items/{limitedId}/images";
            var firstKey = Guid.NewGuid();
            var uploaded = new List<JsonElement>();
            ai.Handler = ImageReply;
            for (short position = 1; position <= 3; position++)
                uploaded.Add(await Binary(browser, path + $"?position={position}", original, "image/png", 201,
                    position == 1 ? firstKey : null));
            Check(uploaded.Select(value => value.GetProperty("position").GetInt16()).SequenceEqual(new short[] { 1, 2, 3 }),
                "uploads accept and preserve positions one through three");
            var callsBefore = ai.Calls;
            var putsBefore = storage.Puts;
            var legacyKey = Guid.NewGuid();
            await Binary(browser, path + "?position=4", original, "image/png", 400);
            using (var scope = factory.Services.CreateScope())
            {
                using var input = new MemoryStream(original, writable: false);
                try
                {
                    await scope.ServiceProvider.GetRequiredService<IImageService>().UploadAsync(actor, Guid.NewGuid(), limitedId, 4,
                        "image/png", input, original.Length, default);
                    throw new InvalidOperationException("Invalid image position should fail.");
                }
                catch (ApiException error) when (error.StatusCode == 400) { Check(true, "service validates upload positions independently of HTTP binding"); }
                var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
                foreach (var legacy in await db.ItemImages.Where(value => value.ItemId == limitedId && value.Position > 1).ToListAsync())
                    legacy.Position += 2;
                var operation = $"image.upload:{limitedId}";
                db.IdempotencyKeys.Add(new IdempotencyKey { ActorUserId = actor, IdempotencyKeyValue = legacyKey,
                    Operation = operation, ResourceType = "image", ResourceId = uploaded[1].GetProperty("id").GetGuid(), ResponseStatus = 201,
                    RequestSha256 = RecoveryWorkflow.RequestHash(operation,
                        new { position = (short)4, mime = "image/png", sha256 = RecoveryWorkflow.Hash(original), length = original.Length }) });
                await db.SaveChangesAsync();
            }
            var legacyReplay = await Binary(browser, path + "?position=4", original, "image/png", 201, legacyKey);
            Check(legacyReplay.GetProperty("id").GetGuid() == uploaded[1].GetProperty("id").GetGuid()
                && legacyReplay.GetProperty("position").GetInt16() == 4 && ai.Calls == callsBefore && storage.Puts == putsBefore,
                "historical upload key at position four replays over HTTP without new AI or storage writes");
            await Binary(browser, path + "?position=4", original, "image/png", 400);
            await Binary(browser, path + "?position=2", original, "image/png", 409);
            var replay = await Binary(browser, path, original, "image/png", 201, firstKey);
            Check(replay.GetProperty("id").GetGuid() == uploaded[0].GetProperty("id").GetGuid()
                && ai.Calls == callsBefore && storage.Puts == putsBefore,
                "fourth uploads and legacy capacity are rejected before AI/storage while replay at capacity succeeds");
            await Send(browser, HttpMethod.Post, $"{path}/{uploaded[1].GetProperty("id").GetGuid()}/retire", new { contentVersion = 1 }, 200);
            await Binary(browser, path + "?position=2", original, "image/png", 201);
            using (var scope = factory.Services.CreateScope())
            {
                var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
                Check(await db.ItemImages.CountAsync(value => value.ItemId == limitedId && value.RetiredAt == null) == 3
                    && await db.ItemImages.AnyAsync(value => value.ItemId == limitedId && value.Position == 5 && value.RetiredAt == null),
                    "retiring one legacy image permits replacement without removing another legacy image or exceeding three active images");
            }
        }
        async Task CheckMultipartSearch()
        {
            using var validation = await User("multipart-validation");
            var inputs = new[] { original, original.Concat(new byte[] { 1 }).ToArray(), original.Concat(new byte[] { 2 }).ToArray() };
            var callsBeforeValidation = ai.Calls;
            var csrf = validation.DefaultRequestHeaders.GetValues("X-CSRF-TOKEN").Single();
            validation.DefaultRequestHeaders.Remove("X-CSRF-TOKEN");
            await Multipart(validation, "/api/search/images", [new byte[100000]], null, 400);
            validation.DefaultRequestHeaders.Add("X-CSRF-TOKEN", csrf);
            await Multipart(validation, "/api/search/images", [], null, 400);
            await Multipart(validation, "/api/search/images", [original, original, original, original], null, 400);
            await Multipart(validation, "/api/search/images", [original, original], null, 415, "application/octet-stream");
            await Multipart(validation, "/api/search/images", [original, []], null, 400);
            await Multipart(validation, "/api/search/images", [original, new byte[BoundedImage.MaxBytes + 1]], null, 413);
            await Multipart(validation, "/api/search/images", [original], new string('x', 2001), 400);
            await Multipart(validation, "/api/search/images", [original], new string('x', 8001), 400);
            await Multipart(validation, "/api/search/images?from=2026-02-01&until=2026-01-01", [original], null, 400);
            await Multipart(validation, "/api/search/images?until=9999-12-31", [original], null, 400);
            await Multipart(validation, "/api/search/images?limit=11", [original], null, 400);
            await Binary(validation, "/api/search/images", original, "image/png", 415);
            using (var malformed = new HttpRequestMessage(HttpMethod.Post, "/api/search/images") { Content = new StringContent("bad multipart") })
            {
                malformed.Content.Headers.ContentType = new MediaTypeHeaderValue("multipart/form-data") { Parameters = { new NameValueHeaderValue("boundary", "missing") } };
                await Response(validation, malformed, 400);
            }
            Check(ai.Calls == callsBeforeValidation, "all multipart images, text and filters are validated before any AI call");

            using var browser = await User("multipart-seeker");
            var buffers = new List<byte[]>();
            var imageQueries = 0;
            var textQueries = 0;
            item = await Get(owner, $"/api/items/{secondId}");
            await Send(owner, HttpMethod.Put, $"/api/items/{secondId}/publication", new { rowVersion = item.GetProperty("rowVersion").GetInt64(), state = "published" }, 200);
            var secondText = await Candidate(secondId, false);
            var firstText = await Candidate(itemId, false);
            ai.Handler = command =>
            {
                Check(!command.Persistent && command.Metadata.GetProperty("area").GetString() == "Campus"
                    && command.Metadata.GetProperty("from").GetString() == "2026-01-01"
                    && command.Metadata.GetProperty("until").GetString() == "2026-01-01", "each search input receives identical filters through transient AI transport");
                if (command.Kind == "search.hybrid.image")
                {
                    Check(command.Body.SequenceEqual(inputs[imageQueries++]) && command.ContentType == "image/png", "all three query images reach the image search worker");
                    buffers.Add(command.Body);
                    return SearchReply(command, [imageCandidate, imageCandidate]);
                }
                using var body = JsonDocument.Parse(command.Body);
                Check(command.Kind == "search.hybrid" && body.RootElement.GetProperty("text").GetString() == "ví màu đen", "description contributes its own text search ranking");
                textQueries++;
                return SearchReply(command, [secondText, firstText]);
            };
            using var scope = factory.Services.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
            var objects = await db.StoredObjects.CountAsync();
            var outbox = await db.IndexOutbox.CountAsync();
            var combined = await Multipart(browser, "/api/search/images?area=Campus&from=2026-01-01&until=2026-01-01&limit=2", inputs, "  ví màu đen  ", 200);
            Check(imageQueries == 3 && textQueries == 1 && combined.GetProperty("mode").GetString() == "combined"
                && combined.GetProperty("searchProfileId").GetString() == "multimodal-fusion-v1", "three images plus description return the combined search contract");
            Check(combined.GetProperty("items").GetArrayLength() == 2
                && combined.GetProperty("items")[0].GetProperty("item").GetProperty("id").GetGuid() == itemId
                && combined.GetProperty("items")[1].GetProperty("rank").GetInt32() == 2,
                "fusion combines all rankings, deduplicates items and honors result limit");
            Check(buffers.All(value => value.All(part => part == 0)) && storage.Puts == putCount
                && await db.StoredObjects.CountAsync() == objects && await db.IndexOutbox.CountAsync() == outbox,
                "multipart raw image buffers are cleared and query input creates no storage or outbox records");
            ai.Handler = command => SearchReply(command, [imageCandidate]);
            var imageOnly = await Multipart(browser, "/api/search/images?limit=1", [original], "  ", 200);
            Check(imageOnly.GetProperty("mode").GetString() == "image" && imageOnly.GetProperty("searchProfileId").GetString() == "image-fusion-v1"
                && imageOnly.GetProperty("items").GetArrayLength() == 1, "optional blank description supports image-only multipart search");
            var filtered = await Multipart(browser, "/api/search/images?area=Other", [original], null, 200);
            Check(filtered.GetProperty("items").GetArrayLength() == 0 && filtered.GetProperty("partial").GetBoolean()
                && !filtered.GetProperty("filtersRelaxed").GetBoolean(), "multipart image search rechecks area filters without relaxation");
            filtered = await Multipart(browser, "/api/search/images?from=2026-01-02", [original], null, 200);
            Check(filtered.GetProperty("items").GetArrayLength() == 0, "multipart image search rechecks date filters");
            var failedBuffers = new List<byte[]>();
            ai.Handler = command =>
            {
                failedBuffers.Add(command.Body);
                return failedBuffers.Count == 1 ? SearchReply(command, [imageCandidate]) : throw new ApiException(503, "Second image worker unavailable.");
            };
            await Multipart(browser, "/api/search/images", inputs, "wallet", 503);
            Check(failedBuffers.Count == 2 && failedBuffers.All(value => value.All(part => part == 0)), "upstream failure fails the whole search and clears every dispatched raw image");
            ai.Handler = command => Task.FromResult(new AiReply(JsonSerializer.SerializeToElement(StubAiGateway.ReplyMetadata(command)), "{\"candidates\":[{}]}"u8.ToArray()));
            await Multipart(browser, "/api/search/images", [original], null, 502);
            ai.Handler = async command =>
            {
                if (command.Kind == "search.hybrid.image") return await SearchReply(command, [imageCandidate]);
                var live = await Get(owner, $"/api/items/{itemId}");
                await Send(owner, HttpMethod.Put, $"/api/items/{itemId}/publication", new { rowVersion = live.GetProperty("rowVersion").GetInt64(), state = "hidden" }, 200);
                return await SearchReply(command, [firstText]);
            };
            var stale = await Multipart(browser, "/api/search/images", [original], "wallet", 200);
            Check(stale.GetProperty("items").GetArrayLength() == 0 && stale.GetProperty("partial").GetBoolean(), "fusion rechecks publication after all AI replies rather than leaking an earlier valid item");
            item = await Get(owner, $"/api/items/{itemId}");
            await Send(owner, HttpMethod.Put, $"/api/items/{itemId}/publication", new { rowVersion = item.GetProperty("rowVersion").GetInt64(), state = "published" }, 200);
            imageCandidate = await Candidate(itemId, true);
            ai.Handler = command => SearchReply(command, [imageCandidate]);
        }
        async Task CheckOutbox(RecoveryMaintenance worker)
        {
            ai.Handler = ImageReply;
            var liveImage = await Binary(owner, imagesPath, original, "image/png", 201);
            await Send(owner, HttpMethod.Post, $"{imagesPath}/{liveImage.GetProperty("id").GetGuid()}/review", new { contentVersion = 1, decision = "approved" }, 200);
            var liveItem = await Get(owner, $"/api/items/{itemId}");
            await Send(owner, HttpMethod.Put, $"/api/items/{itemId}/publication", new { rowVersion = liveItem.GetProperty("rowVersion").GetInt64(), state = "published" }, 200);
            using var scope = factory.Services.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
            await db.IndexOutbox.Where(value => value.Status == "pending" || value.Status == "retry").ExecuteUpdateAsync(update => update
                .SetProperty(value => value.Status, "obsolete").SetProperty(value => value.FinishedAt, DateTimeOffset.UtcNow));
            var current = await Get(owner, $"/api/items/{itemId}");
            await Send(owner, HttpMethod.Put, $"/api/items/{itemId}", new { rowVersion = current.GetProperty("rowVersion").GetInt64(), content = Content("Outbox checksum") }, 200);
            var jobId = await db.IndexOutbox.Where(value => value.Status == "pending").Select(value => value.Id).SingleAsync();
            ai.Handler = command => {
                Check(command.Persistent && command.Kind == "index.upsert", "index command uses persistent transport");
                Check(command.Metadata.GetProperty("dimensions").GetInt32() == 768, "index dispatch uses configured nondefault embedding dimensions");
                Check(RecoveryWorkflow.Hash(RecoveryWorkflow.CanonicalJson(Encoding.UTF8.GetString(command.Body))) == command.Metadata.GetProperty("snapshotSha256").GetString(), "jsonb roundtrip preserves canonical snapshot checksum");
                var metadata = StubAiGateway.ReplyMetadata(command); metadata["committed"] = true;
                return Task.FromResult(new AiReply(JsonSerializer.SerializeToElement(metadata), [], async committed => {
                    using var ackScope = factory.Services.CreateScope();
                    if (committed) Check(await ackScope.ServiceProvider.GetRequiredService<FindieDbContext>().IndexOutbox.AnyAsync(value => value.Id == jobId && value.Status == "succeeded"), "index receipt is ACKed only after business commit");
                }));
            };
            Check(await worker.DispatchOneAsync(default), "outbox dispatched one due job");
            Check(await db.IndexOutbox.AnyAsync(value => value.Id == jobId && value.Status == "succeeded" && value.Attempts == 1), "successful receipt finishes matching lease");
            current = await Get(owner, $"/api/items/{itemId}");
            await Send(owner, HttpMethod.Put, $"/api/items/{itemId}", new { rowVersion = current.GetProperty("rowVersion").GetInt64(), content = Content("Retry outbox") }, 200);
            jobId = await db.IndexOutbox.Where(value => value.Status == "pending").Select(value => value.Id).SingleAsync();
            ai.Handler = _ => throw new ApiException(503, "Broker unavailable.");
            for (var attempt = 1; attempt <= 3; attempt++)
            {
                await worker.DispatchOneAsync(default);
                var status = attempt == 3 ? "failed" : "retry";
                Check(await db.IndexOutbox.AnyAsync(value => value.Id == jobId && value.Status == status && value.Attempts == attempt), "outbox retry attempts are bounded and persisted");
                await db.IndexOutbox.Where(value => value.Id == jobId).ExecuteUpdateAsync(update => update.SetProperty(value => value.NextAttemptAt, DateTimeOffset.UtcNow.AddSeconds(-1)));
            }
            Check(!await worker.DispatchOneAsync(default), "exhausted outbox job is not retried forever");
            current = await Get(owner, $"/api/items/{itemId}");
            await Send(owner, HttpMethod.Put, $"/api/items/{itemId}", new { rowVersion = current.GetProperty("rowVersion").GetInt64(), content = Content("Late index receipt") }, 200);
            var pendingJob = await db.IndexOutbox.AsNoTracking().SingleAsync(value => value.Status == "pending");
            var lease = Guid.NewGuid();
            await db.IndexOutbox.Where(value => value.Id == pendingJob.Id).ExecuteUpdateAsync(update => update
                .SetProperty(value => value.Status, "running").SetProperty(value => value.Attempts, 1)
                .SetProperty(value => value.LeaseToken, lease).SetProperty(value => value.LeaseUntil, DateTimeOffset.UtcNow.AddSeconds(60)));
            var receipt = new Dictionary<string, object?> { ["schemaVersion"] = 1, ["kind"] = "index.upsert", ["succeeded"] = true,
                ["jobId"] = pendingJob.Id, ["leaseToken"] = Guid.NewGuid(), ["itemId"] = itemId, ["documentVersion"] = pendingJob.DocumentVersion,
                ["snapshotSha256"] = pendingJob.PayloadSha256, ["modelId"] = "Qwen/Qwen3-VL-Embedding-2B", ["modelRevision"] = "integration-embedding-revision",
                ["dimensions"] = 768, ["committed"] = true };
            await Accept();
            Check(await db.IndexOutbox.AnyAsync(value => value.Id == pendingJob.Id && value.Status == "running" && value.LeaseToken == lease), "old receipt cannot finish a newer lease");
            receipt["leaseToken"] = lease;
            receipt["snapshotSha256"] = new string('f', 64);
            try { await Accept(); throw new InvalidOperationException("Malformed index receipt should fail."); }
            catch (ApiException error) when (error.StatusCode == 502) { Check(true, "invalid receipt checksum is rejected"); }
            receipt["snapshotSha256"] = pendingJob.PayloadSha256;
            receipt["dimensions"] = 2048;
            try { await Accept(); throw new InvalidOperationException("Mismatched embedding dimensions should fail."); }
            catch (ApiException error) when (error.StatusCode == 502) { Check(true, "receipt with different embedding dimensions is rejected"); }
            receipt["dimensions"] = 768;
            await Accept();
            await Accept();
            Check(await db.IndexOutbox.AnyAsync(value => value.Id == pendingJob.Id && value.Status == "succeeded" && value.Attempts == 1), "receipt without live waiter commits once, duplicate receipt is harmless");
            current = await Get(owner, $"/api/items/{itemId}");
            await Send(owner, HttpMethod.Put, $"/api/items/{itemId}", new { rowVersion = current.GetProperty("rowVersion").GetInt64(), content = Content("Becoming stale") }, 200);
            jobId = await db.IndexOutbox.Where(value => value.Status == "pending").Select(value => value.Id).SingleAsync();
            ai.Handler = async command => {
                var live = await Get(owner, $"/api/items/{itemId}");
                await Send(owner, HttpMethod.Put, $"/api/items/{itemId}", new { rowVersion = live.GetProperty("rowVersion").GetInt64(), content = Content("Changed during index processing") }, 200);
                var metadata = StubAiGateway.ReplyMetadata(command); metadata["committed"] = true;
                return new AiReply(JsonSerializer.SerializeToElement(metadata), []);
            };
            await worker.DispatchOneAsync(default);
            Check(await db.IndexOutbox.AnyAsync(value => value.Id == jobId && value.Status == "obsolete"), "receipt is obsolete if the source changed before business commit");

            async Task Accept()
            {
                using var receiptScope = factory.Services.CreateScope();
                await receiptScope.ServiceProvider.GetRequiredService<IndexReceiptService>().AcceptAsync(JsonSerializer.SerializeToElement(receipt), default);
            }
        }
        async Task<object> Candidate(Guid id, bool image)
        {
            using var scope = factory.Services.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
            var entity = await db.Items.Include(value => value.Images).ThenInclude(value => value.ProcessedObject).SingleAsync(value => value.Id == id);
            var source = image ? entity.Images.Single(value => value.RetiredAt == null) : null;
            return new { itemId = id, documentVersion = entity.DocumentVersion, sourceId = source?.Id ?? id,
                sourceVersion = source?.ContentVersion ?? entity.ContentVersion, sourceSha256 = source?.ProcessedObject?.Sha256 ?? RecoveryWorkflow.Hash(entity.Title + "\n" + entity.PublicDescription) };
        }
        async Task<HttpClient> User(string subject)
        {
            var browser = factory.CreateClient(new WebApplicationFactoryClientOptions { AllowAutoRedirect = false, HandleCookies = true, BaseAddress = new Uri("https://localhost") });
            await login(browser, subject);
            browser.DefaultRequestHeaders.Add("X-CSRF-TOKEN", (await Get(browser, "/api/auth/csrf")).GetProperty("token").GetString());
            return browser;
        }
        Task<AiReply> ImageReply(AiCommand command)
        {
            lastInput = command.Body;
            Check(command.Kind == "image.redact" && !command.Persistent && command.Body.SequenceEqual(original), "original is sent only via transient AI request");
            var remaining = command.Metadata.GetProperty("deadlineAt").GetDateTimeOffset() - DateTimeOffset.UtcNow;
            Check(remaining.TotalSeconds is > 295 and <= 300, "redaction gets a five-minute processing deadline");
            return Task.FromResult(new AiReply(JsonSerializer.SerializeToElement(ImageMetadata(command)), Output.ToArray()));
        }
    }
    static Dictionary<string, object?> ImageMetadata(AiCommand command)
    {
        var metadata = StubAiGateway.ReplyMetadata(command);
        metadata["contentType"] = "image/png"; metadata["sha256"] = RecoveryWorkflow.Hash(Output);
        metadata["width"] = 1; metadata["height"] = 1; metadata["byteSize"] = Output.Length; metadata["sensitiveRegions"] = Array.Empty<object>();
        return metadata;
    }
    static Task<AiReply> SearchReply(AiCommand command, object[] candidates) => Task.FromResult(new AiReply(
        JsonSerializer.SerializeToElement(StubAiGateway.ReplyMetadata(command)), JsonSerializer.SerializeToUtf8Bytes(new { candidates })));
    static object Content(string title) => new { title, publicDescription = "Safe public description", foundArea = "Campus", foundTimePrecision = "date", foundOn = "2026-01-01" };
    static object Create(string title) => new { content = Content(title), custody = new { kind = "person" } };
    static Task<JsonElement> Get(HttpClient client, string path) => Send(client, HttpMethod.Get, path, null, 200);
    static async Task<JsonElement> Send(HttpClient client, HttpMethod method, string path, object? body, int expected)
    {
        using var request = new HttpRequestMessage(method, path);
        if (body is not null) request.Content = JsonContent.Create(body);
        if (method != HttpMethod.Get) request.Headers.Add("Idempotency-Key", Guid.NewGuid().ToString());
        return await Response(client, request, expected);
    }
    static async Task<JsonElement> Binary(HttpClient client, string path, byte[] bytes, string mime, int expected, Guid? key = null)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, path) { Content = new ByteArrayContent(bytes) };
        request.Content.Headers.ContentType = new MediaTypeHeaderValue(mime);
        request.Headers.Add("Idempotency-Key", (key ?? Guid.NewGuid()).ToString());
        return await Response(client, request, expected);
    }
    static async Task<JsonElement> Multipart(HttpClient client, string path, byte[][] images, string? text, int expected, string mime = "image/png")
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, path) { Content = new MultipartFormDataContent() };
        var form = (MultipartFormDataContent)request.Content;
        foreach (var image in images)
        {
            var content = new ByteArrayContent(image);
            content.Headers.ContentType = new MediaTypeHeaderValue(mime);
            form.Add(content, "images", "query.png");
        }
        if (text is not null) form.Add(new StringContent(text), "text");
        return await Response(client, request, expected);
    }
    static async Task<JsonElement> Response(HttpClient client, HttpRequestMessage request, int expected)
    {
        using var response = await client.SendAsync(request);
        var text = await response.Content.ReadAsStringAsync();
        Check((int)response.StatusCode == expected, $"{request.Method} {request.RequestUri}: expected {expected}, got {(int)response.StatusCode}: {text}");
        return text.Length == 0 ? default : JsonDocument.Parse(text).RootElement.Clone();
    }
    static void Check(bool condition, string description)
    {
        if (!condition) throw new InvalidOperationException("FAIL: " + description);
        Interlocked.Increment(ref checks);
    }
}
