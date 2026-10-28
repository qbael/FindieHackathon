using Findie.Api.Models;
using Findie.Api.Services;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Google;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;

namespace Findie.Api.Controllers;

[ApiController]
[Route("api/auth/google")]
public sealed class GoogleAuthController(
    IGoogleAuthService authentication,
    SignInManager<ApplicationUser> signIn,
    IAuthenticationSchemeProvider schemes) : ControllerBase
{
    [HttpGet]
    public async Task<IActionResult> Login([FromQuery] string returnUrl = "/")
    {
        if (!Url.IsLocalUrl(returnUrl))
            return Problem(statusCode: 400, title: "Return URL must be a local path.");
        if (await schemes.GetSchemeAsync(GoogleDefaults.AuthenticationScheme) is null)
            return Problem(statusCode: 503, title: "Google authentication is not configured.");

        await HttpContext.SignOutAsync(IdentityConstants.ExternalScheme);
        var callback = Url.Action(nameof(Callback), new { returnUrl })!;
        return Challenge(signIn.ConfigureExternalAuthenticationProperties(GoogleDefaults.AuthenticationScheme, callback),
            GoogleDefaults.AuthenticationScheme);
    }

    [HttpGet("callback")]
    public async Task<IActionResult> Callback([FromQuery] string returnUrl = "/")
    {
        if (!Url.IsLocalUrl(returnUrl))
            return Problem(statusCode: 400, title: "Return URL must be a local path.");
        try
        {
            if (!await authentication.CompleteSignInAsync())
                return Problem(statusCode: 401, title: "Google authentication failed.");
            return LocalRedirect(returnUrl);
        }
        finally
        {
            await HttpContext.SignOutAsync(IdentityConstants.ExternalScheme);
        }
    }
}
