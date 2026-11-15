# Rejected diagnostic run

The first Timer 2 batching candidate preserved guest memory/registers but overwrote the committed timer marker while applying EOIs. Dialing reported 7,986 timer writes instead of 7,574, so these samples are rejected and excluded from the final comparison. The new marker regression failed before the fix; see regression-before-fix.txt. The pipeline was interrupted before completing its profile/alternating measurements.

The fix marks only EOI records, preserving the timer marker. Final build, tests and measurements are recorded in the parent directory. No rejected implementation was committed.
