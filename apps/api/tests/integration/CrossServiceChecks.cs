using System.Text;
using Findie.Api.Contracts;
using Findie.Api.Data;
using Findie.Api.Infrastructure;
using Findie.Api.Repositories;
using Findie.Api.Services;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;

static class CrossServiceChecks
{
    public static async Task RunAsync(WebApplicationFactory<FindieDbContext> factory)
    {
        var scopes = factory.Services.GetRequiredService<IServiceScopeFactory>();
        var configuration = new ConfigurationBuilder().AddConfiguration(factory.Services.GetRequiredService<IConfiguration>())
            .AddInMemoryCollection(new Dictionary<string, string?> { ["RabbitMq:Uri"] = Environment.GetEnvironmentVariable("FINDIE_TEST_BROKER_URI") }).Build();
        using var gateway = new RabbitMqGateway(configuration, NullLogger<RabbitMqGateway>.Instance, scopes);
        var storage = new StubStorage();
        using var maintenance = new RecoveryMaintenance(scopes, gateway, storage, configuration, NullLogger<RecoveryMaintenance>.Instance);
        var raw = Convert.FromBase64String(Environment.GetEnvironmentVariable("FINDIE_TEST_IMAGE_BASE64")!);
        var actor = await InScope(async services =>
        {
            var db = services.GetRequiredService<FindieDbContext>();
            // Other suites deliberately leave malformed jobs in this disposable fixture.
            await db.IndexOutbox.ExecuteDeleteAsync();
            return (await db.Users.SingleAsync(user => user.NormalizedEmail == "OWNER@EXAMPLE.TEST")).Id;
        });
        await gateway.StartAsync(default);
        try
        {
            var deadline = DateTimeOffset.UtcNow.AddSeconds(20);
            while (!gateway.Ready && DateTimeOffset.UtcNow < deadline) await Task.Delay(50);
            Check(gateway.Ready, ".NET gateway connects to the real Python worker broker");
            var item = await InScope(services => services.GetRequiredService<IItemService>().CreateAsync(actor, Guid.NewGuid(),
                new CreateItemRequest(new ItemInput("Ví da bridge", "Ví da đen nhặt tại phòng E.205", "Bridge-only Campus", "unknown"),
                    new CustodyInput("person")), default));
            var images = new List<ImageResponse>();
            for (short position = 1; position <= 2; position++)
            {
                var uploaded = await InScope(services => Images(services).UploadAsync(actor, Guid.NewGuid(), item.Id, position,
                    "image/png", new MemoryStream(raw, writable: false), raw.Length, default));
                Check(uploaded.ProcessingState == "needs_review", "Python output waits for human review");
                images.Add(await InScope(services => Images(services).ReviewAsync(actor, Guid.NewGuid(), item.Id, uploaded.Id,
                    new ReviewImageRequest(uploaded.ContentVersion, "approved"), default)));
            }
            Check(storage.Puts == 2 && storage.Objects.Values.All(output => !output.SequenceEqual(raw)
                && !Encoding.UTF8.GetString(output).Contains("BRIDGE-PRIVATE-METADATA", StringComparison.Ordinal)),
                "only normalized/masked Python output reaches the R2 test double");
            item = await Current();
            item = await InScope(services => services.GetRequiredService<IItemService>().PublishAsync(actor, Guid.NewGuid(), item.Id,
                new PublicationRequest(item.RowVersion, "published"), default));
            await Flush(item.Id, item.DocumentVersion);
            var text = await Text();
            var image = await Image();
            Check(text.Items.Count == 1 && text.Items[0].Item.Id == item.Id, "real Python text candidate passes .NET provenance checks");
            Check(image.Items.Count == 1 && image.Items[0].Item.Id == item.Id && image.Items[0].Item.Images.Count == 2,
                "real image vectors retrieve the public item with two approved source versions");
            Check(!text.Items[0].Item.CanClaim && !image.Items[0].Item.CanClaim,
                "search results do not allow the poster to claim their own item");
            Check((await InScope(services => Search(services).TextAsync(actor, new SearchRequest("ví", "Wrong campus"), default))).Items.Count == 0,
                "cross-service area filters stay strict");
            await InScope(services => Images(services).RetireAsync(actor, Guid.NewGuid(), item.Id, images[0].Id,
                new RetireImageRequest(images[0].ContentVersion), default));
            item = await Current();
            Check(item.PublicationState == "published" && item.Images.Count == 1, "removing one of two approved images keeps the item public");
            await Flush(item.Id, item.DocumentVersion);
            Check((await Text()).Items.Count == 1 && (await Image()).Items.Count == 1,
                "replacement snapshot retains text and the remaining approved image");
            await InScope(services => Images(services).RetireAsync(actor, Guid.NewGuid(), item.Id, images[1].Id,
                new RetireImageRequest(images[1].ContentVersion), default));
            Check((await Image()).Items.Count == 0, ".NET removes stale image hits before worker catches up");
            item = await Current();
            Check(item.PublicationState == "hidden" && item.Images.Count == 0, "removing the last approved image hides the item");
            await Flush(item.Id, item.DocumentVersion);
            Check((await Text()).Items.Count == 0 && (await Image()).Items.Count == 0,
                "last-image retirement commits a tombstone removing text and image matches across the real service boundary");
            Console.WriteLine("PASS: .NET -> RabbitMQ -> Python -> Ollama test double -> processed-output R2 double; review, full multi-image manifest, search provenance, retirement and tombstone");

            Task<ItemResponse> Current() => InScope(services => services.GetRequiredService<IItemService>().GetAsync(actor, item.Id, default));
            Task<SearchResponse> Text() => InScope(services => Search(services).TextAsync(actor, new SearchRequest("ví da phòng E.205", "Bridge-only Campus"), default));
            Task<SearchResponse> Image() => InScope(services => Search(services).ImageAsync(actor, new ImageSearchFilter { Area = "Bridge-only Campus" },
                "image/png", new MemoryStream(raw, writable: false), raw.Length, default));
        }
        finally
        {
            Array.Clear(raw);
            await gateway.StopAsync(default);
        }

        async Task Flush(Guid itemId, long version)
        {
            for (var remaining = 20; remaining > 0 && await maintenance.DispatchOneAsync(default); remaining--) { }
            var completed = await InScope(services => services.GetRequiredService<FindieDbContext>().IndexOutbox
                .AnyAsync(job => job.ItemId == itemId && job.DocumentVersion == version && job.Status == "succeeded"));
            Check(completed, "real Python receipt follows complete manifest commit and .NET outbox ACK");
        }
        ImageService Images(IServiceProvider services) => new(services.GetRequiredService<IRecoveryRepository>(),
            services.GetRequiredService<RecoveryWorkflow>(), gateway, storage, configuration);
        SearchService Search(IServiceProvider services) => new(services.GetRequiredService<IRecoveryRepository>(), gateway, configuration,
            services.GetRequiredService<RecoveryWorkflow>());
        async Task<T> InScope<T>(Func<IServiceProvider, Task<T>> operation)
        {
            using var scope = scopes.CreateScope();
            return await operation(scope.ServiceProvider);
        }
    }

    static void Check(bool condition, string description)
    {
        if (!condition) throw new InvalidOperationException("FAIL: " + description);
    }
}
