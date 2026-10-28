using System.Net.Mail;
using Findie.Api.Data;
using Findie.Api.Models;
using Microsoft.AspNetCore.Authentication.Google;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;

namespace Findie.Api.Infrastructure;

public static class LocalSeed
{
    public static readonly Guid PointId = Guid.Parse("fd000000-0000-0000-0000-000000000001");

    public static async Task<int> RunAsync(FindieDbContext db, string[] args, TextWriter output)
    {
        string? email = null;
        if (args.Length == 3 && args[0] == "--seed-local" && args[1] == "--staff-email"
            && MailAddress.TryCreate(args[2].Trim(), out var address) && address.Address == args[2].Trim())
            email = address.Address;
        else if (args.Length != 1 || args[0] != "--seed-local")
            throw new ArgumentException("Use --seed-local [--staff-email existing-google-user@example.com].");

        await using var transaction = await db.Database.BeginTransactionAsync();
        await db.Database.ExecuteSqlRawAsync("SELECT pg_advisory_xact_lock(643182016)");
        var point = await db.ReceptionPoints.FindAsync(PointId);
        if (point is null)
        {
            point = new ReceptionPoint { Id = PointId, Name = "Findie Demo Hub",
                PublicAddress = "Quầy demo Findie (môi trường local)",
                Directions = "Điểm thử nghiệm; xác nhận địa điểm thật trước khi bàn giao." };
            db.ReceptionPoints.Add(point);
        }
        ApplicationUser? user = null;
        if (email is not null)
        {
            var normalized = new UpperInvariantLookupNormalizer().NormalizeEmail(email);
            user = await db.Users.SingleOrDefaultAsync(value => value.NormalizedEmail == normalized
                && value.EmailConfirmed && value.DisabledAt == null
                && db.UserLogins.Any(login => login.UserId == value.Id && login.LoginProvider == GoogleDefaults.AuthenticationScheme));
            if (user is not null && point.Active)
            {
                var staff = await db.PointStaff.FindAsync(PointId, user.Id);
                if (staff is null)
                {
                    staff = new PointStaff { PointId = PointId, UserId = user.Id };
                    db.PointStaff.Add(staff);
                }
                staff.CanReceive = staff.CanReturn = true;
                staff.RevokedAt = null;
            }
        }
        await db.SaveChangesAsync();
        await transaction.CommitAsync();
        await output.WriteLineAsync($"Local demo Hub ready: {PointId}. Existing Hub and user profiles preserved.");
        if (email is null)
            await output.WriteLineAsync("Sign in with Google, then run make local-seed STAFF_EMAIL=your-email to grant Hub receive/return permissions.");
        else if (user is null)
        {
            await output.WriteLineAsync("No active verified Google account found. Sign in first, then repeat the staff seed command.");
            return 2;
        }
        else if (!point.Active)
        {
            await output.WriteLineAsync("The existing demo Hub is inactive; no staff permissions changed.");
            return 2;
        }
        else await output.WriteLineAsync("Existing Google account has receive/return permissions at the demo Hub.");
        return 0;
    }
}
