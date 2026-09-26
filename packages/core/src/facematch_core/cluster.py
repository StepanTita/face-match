"""Unsupervised grouping of face embeddings into per-person clusters, with no
reference photos required (used by `facematch group`, unlike `find`'s
against-known-references matching).

Uses single-linkage clustering via a similarity graph + union-find: two faces
merge into the same cluster iff their cosine similarity clears a threshold,
and a cluster is a connected component of that graph. This is simple,
dependency-free (no scikit-learn needed), and matches the shape of the
problem well - "is this the same person" is fundamentally a graph
connectivity question, not something that needs a full ML clustering stack.

Only sized for what a personal archive scan produces (tens of thousands of
faces at most): the pairwise similarity computation is O(n^2), computed in
row blocks to bound peak memory rather than materializing the full N x N
matrix at once.
"""
from __future__ import annotations

import numpy as np

# Cosine-similarity threshold to MERGE two faces into the same person cluster.
# This is deliberately stricter than `find`'s DEFAULT_THRESHOLD (0.38): find
# only ever compares a candidate face against a handful of *known-good*
# reference embeddings of one specific person, so an occasional false
# positive is cheap to catch and reject by eye. Grouping has no reference to
# check against - a bad merge silently folds two different people into one
# cluster with nothing flagging the mistake. That flips the tradeoff: a
# stricter cutoff that risks splitting one person across two clusters
# (annoying but recoverable - just look in both folders) is much safer than
# merging two strangers into one.
DEFAULT_MERGE_THRESHOLD = 0.48

# Clusters smaller than this are treated as "not enough evidence this is a
# recurring person" - a lone face (a stranger in the background, a single bad
# detection) lands in the unclustered bucket instead of getting its own
# person folder.
DEFAULT_MIN_CLUSTER_SIZE = 2


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


def cluster_embeddings(
    embeddings: np.ndarray, threshold: float = DEFAULT_MERGE_THRESHOLD, block_size: int = 1024
) -> np.ndarray:
    """Cluster L2-normalized face embeddings (shape [N, D]) by cosine
    similarity. Returns an array of shape [N] of dense integer cluster
    labels (0..k-1, NOT sorted by size - see `sort_clusters_by_size`).

    Computes pairwise similarity in row blocks so peak memory stays bounded
    by block_size * N rather than N^2, for larger face counts.
    """
    n = embeddings.shape[0]
    uf = _UnionFind(n)
    for start in range(0, n, block_size):
        end = min(start + block_size, n)
        block = embeddings[start:end]
        sims = block @ embeddings.T  # [block, N]
        rows, cols = np.where(sims >= threshold)
        for r, c in zip(rows.tolist(), cols.tolist()):
            i = start + r
            # c > i: skip self-similarity (c == i) and pairs already unioned
            # when the block containing `c` as a row was processed (since the
            # similarity matrix is symmetric, that block already saw column
            # i >= c... only when c < start; for c between start and i it's
            # still a fresh pair, so this is just an optimization, never a
            # correctness requirement - union() is idempotent either way.
            if c > i:
                uf.union(i, c)
    roots = np.array([uf.find(i) for i in range(n)], dtype=np.int64)
    if n == 0:
        return roots
    _, labels = np.unique(roots, return_inverse=True)
    return labels


def sort_clusters_by_size(labels: np.ndarray) -> list[tuple[int, np.ndarray]]:
    """Return [(cluster_label, face_indices)], largest cluster first."""
    if labels.size == 0:
        return []
    unique_labels, counts = np.unique(labels, return_counts=True)
    order = np.argsort(-counts)
    return [(int(unique_labels[i]), np.where(labels == unique_labels[i])[0]) for i in order]
