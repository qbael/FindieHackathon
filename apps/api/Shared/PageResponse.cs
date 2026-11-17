using System.ComponentModel.DataAnnotations;

namespace Findie.Api.Contracts;

public sealed record PageResponse<T>(IReadOnlyList<T> Items, int Page, int PageSize, bool HasMore, int TotalPages);
