/* Binary-search midpoint in C. C ints are fixed-width, so this maps directly
 * onto Congruent's model. The rewrite changes behavior; check it with:
 *   congruent examples/midpoint.c:original examples/midpoint.c:candidate --int-width 32
 * Add --assume 'lo <= hi' to isolate the classic large-input overflow witness.
 */

int original(int lo, int hi) {
    return lo + (hi - lo) / 2;
}

int candidate(int lo, int hi) {
    return (lo + hi) / 2;
}
