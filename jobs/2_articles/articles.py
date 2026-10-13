"""Groups a page's labeled text blocks into articles: column grid
(columns.py), segments merged across columns (segments.py), then captions
moved to their photo's article and the final Article records."""

from bbox import bbox_overlap_area, union_bbox, x_overlap_frac
from columns import build_column_grids
from models import Article, BBox, ImageBlock, TextBlock
from segments import ArticleGroup, merge_column_segments_into_groups

# How much of the narrower of image and article an article must overlap
# horizontally to be a candidate for the image (or its caption). Without it,
# an article merely grazing the image's x-range (a neighbour's wide
# headline in the same row) can win on overlap area.
MIN_COLUMN_NEIGHBOR_X_OVERLAP = 0.3


def extract_articles_from_labeled_blocks(
    text_blocks: list[TextBlock], image_blocks: list[ImageBlock], page_width: float, rules: list[BBox] = ()
) -> tuple[list[float], list[Article]]:
    """Returns (column_boundaries of the main grid, articles).

    Needs the labels (`excluded_short`, `looks_like_headline`,
    `median_body_size`, `is_caption`, `excluded_from_flow`) already set.
    Reading order always comes from column + vertical position, never from
    the layout model, whose order isn't trustworthy. Blocks excluded from
    the flow keep `article_idx=None`. Mutates `text_blocks`."""
    flow_blocks = [b for b in text_blocks if not b.excluded_from_flow]
    boundaries, grids = build_column_grids(flow_blocks, image_blocks, page_width)
    group_list = merge_column_segments_into_groups(grids, rules)
    _rehome_captions(group_list)
    return boundaries, _build_article_records(group_list)


def assign_image_to_article(img_bbox: BBox, articles: list[Article]) -> int | None:
    """Like _best_group_for_image, on the final articles: the one overlapping
    the image most, else the nearest vertically -- among articles sharing its
    column. None if none does (e.g. a full-page background image)."""
    candidates = [a for a in articles if x_overlap_frac(img_bbox, a.bbox_union) >= MIN_COLUMN_NEIGHBOR_X_OVERLAP]
    if not candidates:
        return None
    best_by_area = max(candidates, key=lambda a: bbox_overlap_area(img_bbox, a.bbox_union))
    if bbox_overlap_area(img_bbox, best_by_area.bbox_union) > 0:
        return best_by_area.article_idx
    return min(
        candidates, key=lambda a: max(a.bbox_union.y0 - img_bbox.y1, img_bbox.y0 - a.bbox_union.y1, 0)
    ).article_idx


def _bbox_gap(a: BBox, b: BBox) -> float:
    """Distance between two bboxes' nearest edges (0 if they overlap)."""
    dx = max(a.x0 - b.x1, b.x0 - a.x1, 0)
    dy = max(a.y0 - b.y1, b.y0 - a.y1, 0)
    return (dx * dx + dy * dy) ** 0.5


def _best_group_for_image(img_bbox: BBox, group_list: list[ArticleGroup]) -> ArticleGroup | None:
    """The group a captioned image belongs to: among groups sharing its
    column, the one overlapping it most, else the nearest (image above or
    below its text). Groups of only captions don't count: their flow_bbox is
    the captions' own, which would always win."""
    candidates = [
        g
        for g in group_list
        if any(not b.is_caption for b in g.blocks)
        and x_overlap_frac(img_bbox, g.flow_bbox) >= MIN_COLUMN_NEIGHBOR_X_OVERLAP
    ]
    if not candidates:
        return None
    best_by_area = max(candidates, key=lambda g: bbox_overlap_area(img_bbox, g.flow_bbox))
    if bbox_overlap_area(img_bbox, best_by_area.flow_bbox) > 0:
        return best_by_area
    # Distance to the nearest real block, not to flow_bbox's edge: a wide
    # article's rectangle can reach far past its content in the image's
    # column.
    return min(
        candidates,
        key=lambda g: min(_bbox_gap(img_bbox, b.bbox) for b in g.blocks if not b.is_caption),
    )


def _rehome_captions(group_list: list[ArticleGroup]) -> None:
    """Moves each caption to the article its photo belongs to. A caption
    lands in whatever column it sits in, and a photo nicking the next
    column by a few percent sweeps its caption into an unrelated article
    there."""
    for group in group_list:
        flow_blocks = [b for b in group.blocks if not b.is_caption]
        group.flow_bbox = union_bbox([b.bbox for b in (flow_blocks or group.blocks)])

    for group in group_list:
        for b in list(group.blocks):
            if b.caption_image is None:
                continue
            best_group = _best_group_for_image(b.caption_image.bbox, group_list)
            if best_group is not None and best_group is not group:
                group.blocks.remove(b)
                best_group.blocks.append(b)


def _build_article_records(group_list: list[ArticleGroup]) -> list[Article]:
    """One Article per non-empty group (one of only captions can lose them
    all to _rehome_captions): flow text column by column, top to bottom,
    then the captions."""
    page_articles: list[Article] = []
    for group in group_list:
        blocks = group.blocks
        if not blocks:
            continue
        flow_blocks = [b for b in blocks if not b.is_caption]
        caption_blocks = [b for b in blocks if b.is_caption]
        flow_blocks.sort(key=lambda b: (min(b.columns), b.bbox.y0))
        caption_blocks.sort(key=lambda b: b.bbox.y0)
        ordered_blocks = flow_blocks + caption_blocks
        # The largest headline, not the topmost: a kicker above it is a
        # headline too, but always in a smaller font.
        headline_candidates = [b for b in blocks if b.looks_like_headline]
        headline_block = (
            max(headline_candidates, key=lambda b: b.max_font_size)
            if headline_candidates
            else min(blocks, key=lambda b: b.bbox.y0)
        )
        article = Article(
            article_idx=len(page_articles),
            headline_guess=headline_block.text.split("\n")[0],
            text="\n".join(b.text for b in ordered_blocks),
            bbox_union=union_bbox([b.bbox for b in blocks]),
            columns=sorted({c for b in blocks for c in b.columns}),
        )
        page_articles.append(article)
        for b in blocks:
            b.article_idx = article.article_idx
    return page_articles
