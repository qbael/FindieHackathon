using System.ComponentModel.DataAnnotations;

namespace Findie.Api.Contracts;

public sealed record ConversationResponse(Guid Id, Guid ItemId, Guid ClaimantUserId, Guid ReviewerUserId,
    bool CanSend, DateTimeOffset CreatedAt);
public sealed record SendMessageRequest(Guid ClientMessageId, [Required, StringLength(4000)] string Body);
public sealed record MessageResponse(Guid Id, Guid ConversationId, Guid SenderUserId, Guid ClientMessageId,
    long Sequence, string Body, DateTimeOffset CreatedAt);
public sealed record MessagePage(IReadOnlyList<MessageResponse> Items, long NextAfter, bool HasMore);
