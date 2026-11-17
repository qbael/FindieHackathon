using System.ComponentModel.DataAnnotations;

namespace Findie.Api.Contracts;

public sealed class ItemFilter
{
    [StringLength(200)] public string? Q { get; set; }
    [StringLength(200)] public string? Area { get; set; }
    public DateOnly? From { get; set; }
    public DateOnly? Until { get; set; }
    public Guid? PointId { get; set; }
    [RegularExpression("^(public|mine|managed)$")] public string Scope { get; set; } = "public";
    [Range(1, 10000)] public int Page { get; set; } = 1;
    [Range(1, 100)] public int PageSize { get; set; } = 20;
}

public sealed record CustodyInput(
    [Required, RegularExpression("^(person|point|external)$")] string Kind,
    Guid? PointId = null,
    [StringLength(200)] string? Name = null,
    [StringLength(500)] string? Address = null,
    [StringLength(2000)] string? Instructions = null,
    bool ConfirmedPhysicalReceipt = false);

public sealed record ItemInput(
    [Required, StringLength(200)] string Title,
    [Required, StringLength(5000)] string PublicDescription,
    [Required, StringLength(200)] string FoundArea,
    [Required, RegularExpression("^(unknown|date|exact|range)$")] string FoundTimePrecision,
    DateOnly? FoundOn = null,
    DateTimeOffset? FoundFrom = null,
    DateTimeOffset? FoundUntil = null,
    [Required, StringLength(100)] string FoundTimezone = "Asia/Ho_Chi_Minh",
    IReadOnlyList<string>? VerificationQuestions = null);

public sealed record CreateItemRequest([Required] ItemInput Content, [Required] CustodyInput Custody);
public sealed record UpdateItemRequest([Range(1, long.MaxValue)] long RowVersion, [Required] ItemInput Content);
public sealed record DeleteItemRequest([Range(1, long.MaxValue)] long RowVersion);
public sealed record PublicationRequest([Range(1, long.MaxValue)] long RowVersion,
    [Required, RegularExpression("^(published|hidden)$")] string State);

public sealed record CustodyResponse(string Kind, string? DisplayName, Guid? PointId, string? Name,
    string? PublicAddress, string? Instructions);
public sealed record ImageSummary(Guid Id, short Position, long ContentVersion, string Url);
public sealed record ItemResponse(Guid Id, string Title, string PublicDescription, string FoundArea,
    string FoundTimePrecision, DateOnly? FoundOn, DateTimeOffset? FoundFrom, DateTimeOffset? FoundUntil,
    string FoundTimezone, CustodyResponse Custody, string Lifecycle, string PublicationState,
    long RowVersion, long DocumentVersion, DateTimeOffset CreatedAt, IReadOnlyList<ImageSummary> Images, bool CanClaim, bool CanDelete);
public sealed record QuestionResponse(short Slot, string QuestionText);
public sealed record QuestionSetResponse(long ContentVersion, IReadOnlyList<QuestionResponse> Questions);
