using System.ComponentModel.DataAnnotations;
using System.Net.Mail;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using Findie.Api.Contracts;
using Findie.Api.Data;
using Findie.Api.Services;
using Microsoft.AspNetCore.Authentication.Google;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;

namespace Findie.Api.Infrastructure;

public static class LocalPublicSamples
{
    sealed record Photo(string Path, string Mime, string Sha256);
    sealed record Sample(string SourceId, string SourceUrl, string Path, CreateItemRequest Payload,
        List<Photo> Photos, string Fingerprint, string? LegacyTitleFingerprint);
    sealed record Preview(short Position, Guid ImageId, long ContentVersion, string Sha256, string File);
    sealed record ImportState(Guid ActorId, string Fingerprint, Guid? ItemId, List<Preview> Images)
    {
        [JsonExtensionData] public Dictionary<string, JsonElement>? Metadata { get; init; }
    }
    sealed record Reviewed(List<ReviewedImage> Images);
    sealed record ReviewedImage(Guid ImageId, long ContentVersion, string Sha256);
    sealed record MaskRegion(string Label, int[] Bbox);
    sealed record MaskedCorrection(string SourceFingerprint, Guid ActorId, Guid ItemId, Guid ImageId,
        long ContentVersion, string Sha256, short Position, string File, string MaskedSha256, List<MaskRegion> Regions);
    sealed record CorrectionJournal(string PlanSha256, Preview OldImage, Preview? NewImage = null);
    static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web) { WriteIndented = true };

    public static async Task<int> RunAsync(IServiceProvider services, string[] args, TextWriter output)
    {
        if (args.Length is not (4 or 5) || args[0] != "--import-public-samples" || args[2] != "--actor-email"
            || args.Length == 5 && args[4] is not ("--publish-reviewed" or "--review-only" or "--drafts-only" or "--sync-titles" or "--replace-masked")
            || !MailAddress.TryCreate(args[3], out var email) || email.Address != args[3])
            throw new ArgumentException("Use --import-public-samples PREPARED_JSON --actor-email existing-google-user@example.com [--drafts-only | --review-only | --publish-reviewed | --sync-titles | --replace-masked].");
        var publish = args.Contains("--publish-reviewed", StringComparer.Ordinal);
        var reviewOnly = args.Contains("--review-only", StringComparer.Ordinal);
        var review = publish || reviewOnly;
        var draftsOnly = args.Contains("--drafts-only", StringComparer.Ordinal);
        var syncTitles = args.Contains("--sync-titles", StringComparer.Ordinal);
        var replaceMasked = args.Contains("--replace-masked", StringComparer.Ordinal);
        var samples = JsonSerializer.Deserialize<List<Sample>>(await File.ReadAllTextAsync(args[1]), Json)
            ?? throw new ArgumentException("Prepared samples must be a JSON array.");
        if (samples.Count == 0 || samples.Select(sample => sample.SourceId).Distinct().Count() != samples.Count
            || samples.Select(sample => sample.SourceUrl).Distinct().Count() != samples.Count)
            throw new ArgumentException("Prepared samples must contain distinct source posts.");
        foreach (var sample in samples)
        {
            Validator.ValidateObject(sample.Payload.Content, new ValidationContext(sample.Payload.Content), true);
            Validator.ValidateObject(sample.Payload.Custody, new ValidationContext(sample.Payload.Custody), true);
            if (syncTitles && (sample.LegacyTitleFingerprint is null || sample.LegacyTitleFingerprint == sample.Fingerprint))
                throw new ArgumentException("Title sync requires prepared input with the exact legacy title fingerprint.");
            if (sample.Payload.Custody.Kind != "external" || !sample.Payload.Content.PublicDescription.Contains("DỮ LIỆU MẪU")
                || !sample.Payload.Content.PublicDescription.Contains(sample.SourceUrl) || sample.Photos.Count is < 1 or > 3
                || !File.Exists(sample.Path)) throw new ArgumentException("Run scripts/import_facebook_samples.py --prepare-json first.");
            foreach (var photo in sample.Photos)
            {
                var sourceFolder = System.IO.Path.GetDirectoryName(System.IO.Path.GetFullPath(sample.Path))!;
                var relative = System.IO.Path.GetRelativePath(sourceFolder, System.IO.Path.GetFullPath(photo.Path));
                if (relative == ".." || relative.StartsWith(".." + System.IO.Path.DirectorySeparatorChar)
                    || System.IO.Path.IsPathRooted(relative) || new FileInfo(photo.Path).Length > BoundedImage.MaxBytes
                    || RecoveryWorkflow.Hash(await File.ReadAllBytesAsync(photo.Path)) != photo.Sha256)
                    throw new ArgumentException("Photo changed or is outside its source folder; prepare the input again.");
            }
        }
        Guid actor;
        using (var scope = services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
            var normalized = new UpperInvariantLookupNormalizer().NormalizeEmail(email.Address);
            actor = await db.Users.Where(user => user.NormalizedEmail == normalized && user.EmailConfirmed && user.DisabledAt == null
                && db.UserLogins.Any(login => login.UserId == user.Id && login.LoginProvider == GoogleDefaults.AuthenticationScheme))
                .Select(user => user.Id).SingleOrDefaultAsync();
            if (actor == Guid.Empty) throw new InvalidOperationException("Sign in with the explicitly selected Google account before importing; no account was created.");
        }
        var gateway = services.GetRequiredService<RabbitMqGateway>();
        if (!review && !draftsOnly && !syncTitles)
        {
            await gateway.StartAsync(default);
            var deadline = DateTimeOffset.UtcNow.AddSeconds(30);
            while (!gateway.Ready && DateTimeOffset.UtcNow < deadline) await Task.Delay(100);
            if (!gateway.Ready) throw new InvalidOperationException("AI broker did not become ready.");
        }
        try
        {
            var completed = 0;
            foreach (var sample in samples)
            {
                var folder = System.IO.Path.GetDirectoryName(sample.Path)!;
                var statePath = System.IO.Path.Combine(folder, "local-import-state.json");
                var state = File.Exists(statePath)
                    ? JsonSerializer.Deserialize<ImportState>(await File.ReadAllTextAsync(statePath), Json)!
                    : new ImportState(actor, sample.Fingerprint, null, []);
                if (state.ActorId != actor || state.Fingerprint != sample.Fingerprint
                    && !(syncTitles && state.Fingerprint == sample.LegacyTitleFingerprint))
                    throw new InvalidOperationException("Imported source/account changed; review its existing draft before proceeding.");
                Guid Key(string operation) => new(SHA256.HashData(Encoding.UTF8.GetBytes("source-sample:" + sample.SourceUrl + ":" + operation))[..16]);
                if (state.ItemId is null)
                {
                    if (syncTitles || replaceMasked) throw new InvalidOperationException("This operation requires an existing imported draft.");
                    if (review) continue;
                    var created = await InScope(provider => provider.GetRequiredService<IItemService>()
                        .CreateAsync(actor, Key("create"), sample.Payload, default));
                    state = state with { ItemId = created.Id };
                    await Save();
                }
                var itemId = state.ItemId.Value;
                var item = await InScope(provider => provider.GetRequiredService<IItemService>().GetAsync(actor, itemId, default));
                if (item.PublicationState == "published" && !syncTitles && !replaceMasked) { await output.WriteLineAsync($"Already published: {itemId}"); continue; }
                if (item.PublicationState != "draft" || item.Lifecycle != "active")
                    throw new InvalidOperationException("Imported item is no longer an active draft.");
                if (replaceMasked)
                {
                    var planPath = System.IO.Path.Combine(folder, "masked-correction.json");
                    if (!File.Exists(planPath)) continue;
                    if (new FileInfo(planPath).Length is < 1 or > 16384) throw new InvalidOperationException("Correction plan exceeds its metadata limit.");
                    var planBytes = await File.ReadAllBytesAsync(planPath);
                    var planHash = RecoveryWorkflow.Hash(planBytes);
                    var plan = JsonSerializer.Deserialize<MaskedCorrection>(planBytes, Json)!;
                    if (plan.SourceFingerprint != sample.Fingerprint || plan.ActorId != actor || plan.ItemId != itemId
                        || plan.Position is < 1 or > 3 || plan.ContentVersion < 1 || plan.MaskedSha256 == plan.Sha256
                        || string.IsNullOrWhiteSpace(plan.File) || System.IO.Path.GetFileName(plan.File) != plan.File
                        || plan.Regions is not { Count: > 0 and <= 32 } || plan.Regions.Any(region =>
                            region.Label is not ("face" or "identity_number" or "phone" or "address" or "qr_code" or "barcode")
                            || region.Bbox is not { Length: 4 } || region.Bbox.Any(value => value is < 0 or > 1000)
                            || region.Bbox[0] >= region.Bbox[2] || region.Bbox[1] >= region.Bbox[3]))
                        throw new InvalidOperationException("Masked correction plan does not match this imported draft or has invalid regions.");
                    var maskedPath = System.IO.Path.Combine(folder, plan.File);
                    var maskedInfo = new FileInfo(maskedPath);
                    if (maskedInfo.LinkTarget is not null || maskedInfo.Length is < 1 or > BoundedImage.MaxBytes)
                        throw new InvalidOperationException("Masked derivative must be a bounded local PNG file.");
                    var masked = await File.ReadAllBytesAsync(maskedPath);
                    if (!BoundedImage.Signature(masked, "image/png") || RecoveryWorkflow.Hash(masked) != plan.MaskedSha256)
                        throw new InvalidOperationException("Masked derivative changed since its correction plan was reviewed.");
                    var journalPath = System.IO.Path.Combine(folder, $"masked-correction-{planHash}.journal.json");
                    CorrectionJournal journal;
                    if (File.Exists(journalPath))
                    {
                        journal = JsonSerializer.Deserialize<CorrectionJournal>(await File.ReadAllTextAsync(journalPath), Json)!;
                        if (journal.PlanSha256 != planHash) throw new InvalidOperationException("Correction journal belongs to a different plan.");
                    }
                    else
                    {
                        var old = state.Images.Single(image => image.Position == plan.Position);
                        if (old.ImageId != plan.ImageId || old.ContentVersion != plan.ContentVersion || old.Sha256 != plan.Sha256)
                            throw new InvalidOperationException("Correction plan does not identify the exact imported processed image.");
                        var images = await InScope(provider => provider.GetRequiredService<IImageService>().ListAsync(actor, itemId, default));
                        if (!images.Any(image => image.Id == old.ImageId && image.Position == old.Position && image.ContentVersion == old.ContentVersion && image.PreviewUrl is not null))
                            throw new InvalidOperationException("Processed image changed before correction.");
                        var current = await InScope(provider => provider.GetRequiredService<IImageService>().ContentAsync(actor, itemId, old.ImageId, default));
                        if (RecoveryWorkflow.Hash(current.Bytes) != old.Sha256
                            || RecoveryWorkflow.Hash(await File.ReadAllBytesAsync(System.IO.Path.Combine(folder, old.File))) != old.Sha256)
                            throw new InvalidOperationException("Current processed image or retained preview changed before correction.");
                        journal = new CorrectionJournal(planHash, old);
                        await SaveJson(journalPath, journal);
                    }
                    var previous = journal.OldImage;
                    var saved = state.Images.Single(image => image.Position == plan.Position);
                    if (previous.ImageId != plan.ImageId || previous.ContentVersion != plan.ContentVersion
                        || previous.Sha256 != plan.Sha256 || previous.Position != plan.Position
                        || saved != previous && saved != journal.NewImage)
                        throw new InvalidOperationException("Imported image state changed outside this correction journal.");
                    if (journal.NewImage is null)
                    {
                        await InScope(provider => provider.GetRequiredService<IImageService>().RetireAsync(actor,
                            Key($"mask:{planHash}:retire"), itemId, previous.ImageId, new RetireImageRequest(previous.ContentVersion), default));
                        await using var body = new MemoryStream(masked, writable: false);
                        var replacement = await InScope(provider => provider.GetRequiredService<IImageService>().UploadAsync(actor,
                            Key($"mask:{planHash}:upload"), itemId, plan.Position, "image/png", body, body.Length, default));
                        var processed = await InScope(provider => provider.GetRequiredService<IImageService>().ContentAsync(actor, itemId, replacement.Id, default));
                        var extension = processed.ContentType switch { "image/png" => "png", "image/webp" => "webp", _ => "jpg" };
                        var file = $"processed-{replacement.Id}.{extension}";
                        await File.WriteAllBytesAsync(System.IO.Path.Combine(folder, file), processed.Bytes);
                        journal = journal with { NewImage = new Preview(plan.Position, replacement.Id, replacement.ContentVersion, RecoveryWorkflow.Hash(processed.Bytes), file) };
                        await SaveJson(journalPath, journal);
                    }
                    var next = journal.NewImage!;
                    var latest = await InScope(provider => provider.GetRequiredService<IImageService>().ContentAsync(actor, itemId, next.ImageId, default));
                    if (RecoveryWorkflow.Hash(latest.Bytes) != next.Sha256
                        || RecoveryWorkflow.Hash(await File.ReadAllBytesAsync(System.IO.Path.Combine(folder, next.File))) != next.Sha256)
                        throw new InvalidOperationException("Replacement output changed before import state was saved.");
                    if (saved == next)
                    {
                        if (state.Metadata?.ContainsKey("privacyCorrection:" + planHash) != true)
                            throw new InvalidOperationException("Replacement import state is missing its correction audit.");
                        await output.WriteLineAsync($"{++completed}/{samples.Count}: verified existing masked replacement {next.ImageId}.");
                        continue;
                    }
                    var reviewedPath = System.IO.Path.Combine(folder, "reviewed.json");
                    if (File.Exists(reviewedPath))
                    {
                        var archive = System.IO.Path.Combine(folder, $"reviewed-before-mask-{planHash}.json");
                        if (File.Exists(archive) && RecoveryWorkflow.Hash(await File.ReadAllBytesAsync(archive)) != RecoveryWorkflow.Hash(await File.ReadAllBytesAsync(reviewedPath)))
                            throw new InvalidOperationException("A different reviewed manifest already exists in the correction archive.");
                        File.Move(reviewedPath, archive, true);
                    }
                    var metadata = state.Metadata ?? [];
                    metadata["privacyCorrection:" + planHash] = JsonSerializer.SerializeToElement(new { planHash, plan, previous, replacement = next }, Json);
                    state = state with { Images = state.Images.Select(image => image.Position == plan.Position ? next : image).ToList(), Metadata = metadata };
                    await Save();
                    await output.WriteLineAsync($"{++completed}/{samples.Count}: replaced masked image {next.ImageId}; awaiting visual review in draft.");
                    continue;
                }
                if (syncTitles)
                {
                    var changed = await InScope(async provider =>
                    {
                        var db = provider.GetRequiredService<FindieDbContext>();
                        var current = await db.Items.AsNoTracking().Include(value => value.VerificationQuestions)
                            .SingleAsync(value => value.Id == itemId);
                        if (current.PostedBy != actor || current.PublicationState != "draft" || current.Lifecycle != "active")
                            throw new InvalidOperationException("Title sync requires the selected account's active draft.");
                        var title = sample.Payload.Content.Title;
                        if (current.Title == title) return false;
                        if (current.Title != "[Mẫu] " + title)
                            throw new InvalidOperationException("Existing title changed beyond the sample prefix; review the draft.");
                        var content = new ItemInput(title, current.PublicDescription, current.FoundArea, current.FoundTimePrecision,
                            current.FoundOn, current.FoundFrom, current.FoundUntil, current.FoundTimezone,
                            current.VerificationQuestions.OrderBy(question => question.Slot).Select(question => question.QuestionText).ToList());
                        await provider.GetRequiredService<IItemService>().UpdateAsync(actor, Key("remove-sample-title:" + sample.Fingerprint),
                            itemId, new UpdateItemRequest(current.RowVersion, content), default);
                        return true;
                    });
                    if (state.Fingerprint != sample.Fingerprint)
                    {
                        state = state with { Fingerprint = sample.Fingerprint };
                        await Save();
                    }
                    await output.WriteLineAsync($"{++completed}/{samples.Count}: {(changed ? "updated" : "verified")} title {itemId}.");
                    continue;
                }
                if (draftsOnly)
                {
                    await output.WriteLineAsync($"{++completed}/{samples.Count}: saved draft {itemId}; source photos retained locally for processing.");
                    continue;
                }
                if (!review)
                {
                    for (short position = 1; position <= sample.Photos.Count; position++)
                    {
                        if (state.Images.Any(image => image.Position == position)) continue;
                        var photo = sample.Photos[position - 1];
                        await using var stream = File.OpenRead(photo.Path);
                        var image = await InScope(provider => provider.GetRequiredService<IImageService>().UploadAsync(actor,
                            Key($"image:{position}:{photo.Sha256}"), itemId, position, photo.Mime, stream, stream.Length, default));
                        var processed = await InScope(provider => provider.GetRequiredService<IImageService>().ContentAsync(actor, itemId, image.Id, default));
                        var extension = processed.ContentType switch { "image/png" => "png", "image/webp" => "webp", _ => "jpg" };
                        var file = $"processed-{image.Id}.{extension}";
                        await File.WriteAllBytesAsync(System.IO.Path.Combine(folder, file), processed.Bytes);
                        state.Images.Add(new Preview(position, image.Id, image.ContentVersion, RecoveryWorkflow.Hash(processed.Bytes), file));
                        await Save();
                    }
                    await output.WriteLineAsync($"{++completed}/{samples.Count}: draft {itemId}; inspect processed photos in {folder}.");
                }
                else
                {
                    var reviewPath = System.IO.Path.Combine(folder, "reviewed.json");
                    if (!File.Exists(reviewPath)) { await output.WriteLineAsync($"Awaiting reviewed.json: {itemId}"); continue; }
                    var reviewed = JsonSerializer.Deserialize<Reviewed>(await File.ReadAllTextAsync(reviewPath), Json)!;
                    if (state.Images.Count != sample.Photos.Count || reviewed.Images.Count != state.Images.Count
                        || reviewed.Images.Select(image => image.ImageId).Distinct().Count() != reviewed.Images.Count)
                        throw new InvalidOperationException("Review must cover every exact processed image.");
                    foreach (var image in state.Images)
                    {
                        if (!reviewed.Images.Any(value => value.ImageId == image.ImageId && value.ContentVersion == image.ContentVersion && value.Sha256 == image.Sha256))
                            throw new InvalidOperationException("Reviewed image identity/version/hash does not match the processed preview.");
                        var processed = await InScope(provider => provider.GetRequiredService<IImageService>().ContentAsync(actor, itemId, image.ImageId, default));
                        if (RecoveryWorkflow.Hash(processed.Bytes) != image.Sha256
                            || RecoveryWorkflow.Hash(await File.ReadAllBytesAsync(System.IO.Path.Combine(folder, image.File))) != image.Sha256)
                            throw new InvalidOperationException("Processed preview changed since visual review.");
                        await InScope(provider => provider.GetRequiredService<IImageService>().ReviewAsync(actor, Key($"review:{image.ImageId}:{image.ContentVersion}"),
                            itemId, image.ImageId, new ReviewImageRequest(image.ContentVersion, "approved"), default));
                    }
                    if (publish)
                    {
                        item = await InScope(provider => provider.GetRequiredService<IItemService>().GetAsync(actor, itemId, default));
                        await InScope(provider => provider.GetRequiredService<IItemService>().PublishAsync(actor, Key("publish"), itemId,
                            new PublicationRequest(item.RowVersion, "published"), default));
                    }
                    await output.WriteLineAsync($"{++completed}/{samples.Count}: {(publish ? "published" : "kept draft with")} visually reviewed sample {itemId}.");
                }

                Task Save() => SaveJson(statePath, state);
            }
        }
        finally { if (!review && !draftsOnly && !syncTitles) await gateway.StopAsync(default); }
        return 0;

        async Task<T> InScope<T>(Func<IServiceProvider, Task<T>> work)
        {
            using var scope = services.CreateScope();
            return await work(scope.ServiceProvider);
        }
    }

    static async Task SaveJson<T>(string path, T value)
    {
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        await File.WriteAllTextAsync(temporary, JsonSerializer.Serialize(value, Json) + "\n");
        File.Move(temporary, path, true);
    }
}
