using System.ComponentModel.DataAnnotations;

namespace Findie.Api.Contracts;

public sealed record ConversationSummary(Guid Id, Guid ItemId, long LatestSequence, Guid LatestSenderUserId, string LatestBody, DateTimeOffset LatestCreatedAt);
public sealed record NotificationSummaryResponse(int PendingRequestsCount, int DecidedRequestsCount, IReadOnlyList<ConversationSummary> Conversations);
