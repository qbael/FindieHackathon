using System.ComponentModel.DataAnnotations;

namespace Findie.Api.Contracts;

public sealed record ReturnItemRequest([Range(1, long.MaxValue)] long RowVersion,
    bool ConfirmedPhysicalHandover, Guid? ClaimId = null, Guid? RecipientUserId = null,
    [StringLength(2000)] string? VerificationNote = null);
public sealed record CustodyEventResponse(Guid Id, Guid ItemId, string EventKind, long CustodyVersion,
    DateTimeOffset OccurredAt);
