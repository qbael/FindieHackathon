using System.ComponentModel.DataAnnotations;

namespace Findie.Api.Contracts;

public sealed record CreateIntakeRequest(Guid TargetPointId, [Range(1, long.MaxValue)] long RowVersion);
public sealed record IntakeDecisionRequest([Required, RegularExpression("^(received|rejected)$")] string Decision,
    [Range(1, long.MaxValue)] long RowVersion, bool ConfirmedPhysicalReceipt = false,
    [StringLength(2000)] string? Note = null);
public sealed record IntakeResponse(Guid Id, Guid ItemId, Guid RequestedBy, Guid TargetPointId,
    string Status, bool Stale, DateTimeOffset CreatedAt, DateTimeOffset? DecidedAt, string? DecisionNote, long ItemRowVersion);
