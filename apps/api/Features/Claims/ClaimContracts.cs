using System.ComponentModel.DataAnnotations;

namespace Findie.Api.Contracts;

public sealed record ClaimAnswerInput([Range(1, 3)] short Slot, [StringLength(2000)] string? AnswerText);
public sealed record CreateClaimRequest([Range(1, long.MaxValue)] long ContentVersion, IReadOnlyList<ClaimAnswerInput>? Answers = null);
public sealed record DecisionRequest([Required, RegularExpression("^(approved|rejected)$")] string Decision,
    [StringLength(2000)] string? Note = null);
public sealed record ClaimAnswerResponse(short Slot, string QuestionText, string? AnswerText);
public sealed record ClaimResponse(Guid Id, Guid ItemId, Guid ClaimantUserId, Guid ReviewerUserId,
    string Status, bool Stale, DateTimeOffset CreatedAt, DateTimeOffset? DecidedAt, string? DecisionNote,
    Guid? ConversationId, IReadOnlyList<ClaimAnswerResponse> Answers);
