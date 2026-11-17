using System.ComponentModel.DataAnnotations;

namespace Findie.Api.Contracts;

public sealed record ImageResponse(Guid Id, Guid ItemId, short Position, long ContentVersion,
    string ProcessingState, string ReviewState, string? FailureCode, string? PreviewUrl);
public sealed record ReviewImageRequest([Range(1, long.MaxValue)] long ContentVersion,
    [Required, RegularExpression("^(approved|rejected)$")] string Decision);
public sealed record RetireImageRequest([Range(1, long.MaxValue)] long ContentVersion);
