using Findie.Api.Contracts;
using Findie.Api.Models;
using Findie.Api.Repositories;
using Microsoft.EntityFrameworkCore;

namespace Findie.Api.Services;

public sealed class UserService(IUserRepository users) : IUserService
{
    public async Task<UserProfile?> GetProfileAsync(Guid userId, CancellationToken cancellationToken)
    {
        var user = await users.GetByIdAsync(userId, cancellationToken);
        return user is null || user.DisabledAt is not null ? null : ToProfile(user);
    }

    public async Task<UserProfile?> UpdateProfileAsync(Guid userId, UpdateUserRequest request, CancellationToken cancellationToken)
    {
        var displayName = request.DisplayName?.Trim();
        if (string.IsNullOrEmpty(displayName) || displayName.Length > 120)
            throw new ArgumentException("Display name must contain 1 to 120 characters.", nameof(request));

        var user = await users.GetByIdAsync(userId, cancellationToken);
        if (user is null || user.DisabledAt is not null)
            return null;

        user.DisplayName = displayName;
        var result = await users.UpdateAsync(user);
        if (!result.Succeeded)
        {
            if (result.Errors.Any(error => error.Code == "ConcurrencyFailure"))
                throw new DbUpdateConcurrencyException("The profile changed; reload before saving.");
            throw new InvalidOperationException("The profile could not be updated.");
        }
        return ToProfile(user);
    }

    private static UserProfile ToProfile(ApplicationUser user) => new(user.Id, user.Email, user.DisplayName, user.CreatedAt);
}
