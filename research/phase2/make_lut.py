"""Phase 2: generate a 33^3 brand .cube from code (no third-party LUT pack needed).
House look: gentle S-curve, warm highlights / cool-navy shadows split-tone, -8% saturation."""
import numpy as np, sys
N = 33; g = np.linspace(0, 1, N)
out = sys.argv[1] if len(sys.argv) > 1 else "/home/ubuntu/phase2_out/brand_v0.cube"
with open(out, "w") as f:
    f.write('TITLE "most_amazing_brand_v0"\nLUT_3D_SIZE 33\n')
    for b in g:
        for gg in g:
            for r in g:  # .cube order: R fastest
                c = np.array([r, gg, b])
                c = c + 0.12 * (c - 0.5) * (1 - np.abs(2 * c - 1))           # S-curve
                l = c @ [0.2126, 0.7152, 0.0722]
                c = l + 0.92 * (c - l)                                        # desat 8%
                c = c + (1 - l) * np.array([-0.02, 0.0, 0.035]) + l * np.array([0.03, 0.012, -0.03])  # split-tone
                f.write("%.6f %.6f %.6f\n" % tuple(np.clip(c, 0, 1)))
print(out)
