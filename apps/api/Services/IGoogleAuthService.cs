namespace Findie.Api.Services;

public interface IGoogleAuthService
{
    Task<bool> CompleteSignInAsync();
}
