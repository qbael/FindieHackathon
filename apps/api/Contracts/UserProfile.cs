using System.ComponentModel.DataAnnotations;

namespace Findie.Api.Contracts;

public sealed record UserProfile(Guid Id, string? Email, string DisplayName, DateTimeOffset CreatedAt);

public sealed record UpdateUserRequest([Required, StringLength(120)] string DisplayName);
