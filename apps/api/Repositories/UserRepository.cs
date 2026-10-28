using Findie.Api.Data;
using Findie.Api.Models;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;

namespace Findie.Api.Repositories;

public sealed class UserRepository(FindieDbContext database, UserManager<ApplicationUser> users) : IUserRepository
{
    public Task<ApplicationUser?> GetByIdAsync(Guid id, CancellationToken cancellationToken) =>
        database.Users.SingleOrDefaultAsync(user => user.Id == id, cancellationToken);

    public Task<IdentityResult> UpdateAsync(ApplicationUser user) => users.UpdateAsync(user);

    public Task<ApplicationUser?> FindByLoginAsync(string provider, string providerKey) =>
        users.FindByLoginAsync(provider, providerKey);

    public async Task<IdentityResult> CreateWithLoginAsync(ApplicationUser user, UserLoginInfo login)
    {
        await using var transaction = await database.Database.BeginTransactionAsync();
        var result = await users.CreateAsync(user);
        if (!result.Succeeded)
            return result;

        result = await users.AddLoginAsync(user, login);
        if (result.Succeeded)
            await transaction.CommitAsync();
        return result;
    }
}
