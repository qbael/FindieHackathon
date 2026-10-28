using Findie.Api.Contracts;
using Findie.Api.Infrastructure;
using Findie.Api.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;

namespace Findie.Api.Controllers;

[Route("api/search")]
[EnableRateLimiting("images")]
public sealed class SearchController(ISearchService search) : RecoveryController
{
    [HttpPost]
    public async Task<ActionResult<SearchResponse>> Text(SearchRequest request, CancellationToken ct) => Ok(await search.TextAsync(request, ct));
    [HttpPost("image")]
    [RequestSizeLimit(BoundedImage.MaxBytes)]
    public async Task<ActionResult<SearchResponse>> Image([FromQuery] ImageSearchFilter filter, CancellationToken ct) =>
        Ok(await search.ImageAsync(filter, Request.ContentType, Request.Body, Request.ContentLength, ct));
}
