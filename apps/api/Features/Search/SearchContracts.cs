using System.ComponentModel.DataAnnotations;

namespace Findie.Api.Contracts;

public sealed record SearchRequest([Required, StringLength(2000)] string Text,
    [StringLength(200)] string? Area = null, DateOnly? From = null, DateOnly? Until = null,
    [Range(1, 10)] int Limit = 10, [StringLength(33)] string? LostAt = null);
public sealed class ImageSearchFilter
{
    [StringLength(200)] public string? Area { get; set; }
    public DateOnly? From { get; set; }
    public DateOnly? Until { get; set; }
    [StringLength(33)] public string? LostAt { get; set; }
    [Range(1, 10)] public int Limit { get; set; } = 10;
}
public sealed record SearchHit(int Rank, ItemResponse Item);
public sealed record SearchResponse(IReadOnlyList<SearchHit> Items, string Mode, string SearchProfileId,
    int SearchProfileVersion, bool Partial, bool FiltersRelaxed, string FallbackUrl, string RankingMethod = "similarity_fallback");
