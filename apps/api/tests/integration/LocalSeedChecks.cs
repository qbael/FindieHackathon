using Findie.Api.Data;
using Findie.Api.Infrastructure;
using Microsoft.EntityFrameworkCore;

static class LocalSeedChecks
{
    public static async Task RunAsync(FindieDbContext db)
    {
        using var output = new StringWriter();
        var userCount = await db.Users.CountAsync();
        Check(await LocalSeed.RunAsync(db, ["--seed-local", "--staff-email", "not-signed-in@example.test"], output) == 2,
            "missing account asks for Google sign-in");
        Check(await db.Users.CountAsync() == userCount, "seed never invents an account");
        await LocalSeed.RunAsync(db, ["--seed-local"], output);
        Check(await db.ReceptionPoints.CountAsync(point => point.Id == LocalSeed.PointId) == 1, "Hub seed is idempotent");
        var point = await db.ReceptionPoints.SingleAsync(value => value.Id == LocalSeed.PointId);
        point.Name = "Keep configured Hub name";
        await db.SaveChangesAsync();
        var user = await db.Users.SingleAsync(value => value.NormalizedEmail == "OWNER@EXAMPLE.TEST");
        var name = user.DisplayName;
        var seed = new[] { "--seed-local", "--staff-email", "OWNER@example.test" };
        Check(await LocalSeed.RunAsync(db, seed, output) == 0 && await LocalSeed.RunAsync(db, seed, output) == 0,
            "existing verified Google user can receive repeated explicit staff grants");
        var staff = await db.PointStaff.SingleAsync(value => value.PointId == LocalSeed.PointId && value.UserId == user.Id);
        Check(staff.CanReceive && staff.CanReturn && staff.RevokedAt == null, "staff has Hub receive/return permissions");
        Check(point.Name == "Keep configured Hub name" && user.DisplayName == name && await db.Users.CountAsync() == userCount,
            "seed preserves Hub configuration and user profiles");
        Check(await LocalSeed.RunAsync(db, ["--seed-local", "--staff-email", "claimant@example.test"], output) == 2,
            "non-Google account is not granted staff permissions");
        point.Active = false;
        staff.CanReceive = false;
        await db.SaveChangesAsync();
        Check(await LocalSeed.RunAsync(db, seed, output) == 2 && !staff.CanReceive && !point.Active,
            "seed does not reactivate an inactive Hub");
        point.Active = true;
        await db.SaveChangesAsync();
        Console.WriteLine("PASS: local Hub/staff seed is idempotent, keeps profiles and requires an existing active Google user");
    }

    static void Check(bool condition, string description)
    {
        if (!condition) throw new InvalidOperationException("FAIL: " + description);
    }
}
