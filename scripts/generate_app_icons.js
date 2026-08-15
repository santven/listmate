const { Resvg } = require("@resvg/resvg-js");
const fs = require("fs");
const path = require("path");

const fullIconSvg = `
<svg width="1024" height="1024" viewBox="0 0 1024 1024" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="bgGrad" x1="0" y1="0" x2="1024" y2="1024" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#48C774"/>
      <stop offset="100%" stop-color="#289454"/>
    </linearGradient>
    <linearGradient id="badgeGrad" x1="600" y1="200" x2="840" y2="440" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#FFD166"/>
      <stop offset="100%" stop-color="#F49D37"/>
    </linearGradient>
  </defs>

  <!-- Background rounded squircle for full icon -->
  <rect width="1024" height="1024" rx="230" fill="url(#bgGrad)"/>

  <!-- Icon group -->
  <g transform="translate(0, 10)">
    <!-- Checklist sheet inside cart -->
    <rect x="430" y="270" width="220" height="250" rx="24" fill="#FFFFFF" fill-opacity="0.96"/>
    
    <!-- Checklist lines -->
    <rect x="500" y="325" width="115" height="18" rx="9" fill="#289454"/>
    <circle cx="468" cy="334" r="9" fill="#289454"/>
    
    <rect x="500" y="380" width="115" height="18" rx="9" fill="#289454"/>
    <circle cx="468" cy="389" r="9" fill="#289454"/>
    
    <rect x="500" y="435" width="85" height="18" rx="9" fill="#289454"/>
    <circle cx="468" cy="444" r="9" fill="#289454"/>

    <!-- Main shopping cart body -->
    <path d="M230 330 H320 L400 640 H740 L810 400 H355" 
          stroke="#FFFFFF" stroke-width="44" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
    
    <!-- Cart wheels -->
    <circle cx="430" cy="745" r="44" fill="#FFFFFF"/>
    <circle cx="705" cy="745" r="44" fill="#FFFFFF"/>

    <!-- Checkmark badge top right -->
    <circle cx="730" cy="340" r="70" fill="url(#badgeGrad)"/>
    <path d="M695 340 L720 365 L765 315" stroke="#FFFFFF" stroke-width="18" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
  </g>
</svg>
`;

const adaptiveFgSvg = `
<svg width="1024" height="1024" viewBox="0 0 1024 1024" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="badgeGrad" x1="600" y1="200" x2="840" y2="440" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#FFD166"/>
      <stop offset="100%" stop-color="#F49D37"/>
    </linearGradient>
  </defs>

  <!-- Centered safe-zone group (scaled to 65% of canvas) -->
  <g transform="translate(179, 179) scale(0.65)">
    <!-- Checklist sheet inside cart -->
    <rect x="430" y="270" width="220" height="250" rx="24" fill="#FFFFFF" fill-opacity="0.96"/>
    
    <!-- Checklist lines -->
    <rect x="500" y="325" width="115" height="18" rx="9" fill="#289454"/>
    <circle cx="468" cy="334" r="9" fill="#289454"/>
    
    <rect x="500" y="380" width="115" height="18" rx="9" fill="#289454"/>
    <circle cx="468" cy="389" r="9" fill="#289454"/>
    
    <rect x="500" y="435" width="85" height="18" rx="9" fill="#289454"/>
    <circle cx="468" cy="444" r="9" fill="#289454"/>

    <!-- Main shopping cart body -->
    <path d="M230 330 H320 L400 640 H740 L810 400 H355" 
          stroke="#FFFFFF" stroke-width="44" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
    
    <!-- Cart wheels -->
    <circle cx="430" cy="745" r="44" fill="#FFFFFF"/>
    <circle cx="705" cy="745" r="44" fill="#FFFFFF"/>

    <!-- Checkmark badge top right -->
    <circle cx="730" cy="340" r="70" fill="url(#badgeGrad)"/>
    <path d="M695 340 L720 365 L765 315" stroke="#FFFFFF" stroke-width="18" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
  </g>
</svg>
`;

const adaptiveBgSvg = `
<svg width="1024" height="1024" viewBox="0 0 1024 1024" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="bgGrad" x1="0" y1="0" x2="1024" y2="1024" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#48C774"/>
      <stop offset="100%" stop-color="#289454"/>
    </linearGradient>
  </defs>
  <rect width="1024" height="1024" fill="url(#bgGrad)"/>
</svg>
`;

async function main() {
    const renderSvg = (svg, size) => {
        const resvg = new Resvg(svg, { fitTo: { mode: "width", value: size } });
        return resvg.render().asPng();
    };

    const master1024 = renderSvg(fullIconSvg, 1024);

    fs.writeFileSync("assets/icon.png", master1024);
    fs.writeFileSync("resources/icon.png", master1024);
    fs.writeFileSync("static/icon-512.png", renderSvg(fullIconSvg, 512));
    fs.writeFileSync("static/icon-192.png", renderSvg(fullIconSvg, 192));

    const webpSizes = [48, 72, 96, 128, 192, 256, 512];
    for (const sz of webpSizes) {
        fs.writeFileSync(`icons/icon-${sz}.webp`, renderSvg(fullIconSvg, sz));
    }

    const androidDensities = [
        ["mipmap-mdpi", 48, 108],
        ["mipmap-hdpi", 72, 162],
        ["mipmap-xhdpi", 96, 216],
        ["mipmap-xxhdpi", 144, 324],
        ["mipmap-xxxhdpi", 192, 432]
    ];

    const androidTargets = ["android/app/src/main/res", "icon-override"];

    for (const target of androidTargets) {
        for (const [folder, legacySize, adaptiveSize] of androidDensities) {
            const dir = path.join(target, folder);
            fs.mkdirSync(dir, { recursive: true });

            fs.writeFileSync(path.join(dir, "ic_launcher.png"), renderSvg(fullIconSvg, legacySize));
            fs.writeFileSync(path.join(dir, "ic_launcher_round.png"), renderSvg(fullIconSvg, legacySize));
            fs.writeFileSync(path.join(dir, "ic_launcher_foreground.png"), renderSvg(adaptiveFgSvg, adaptiveSize));
            fs.writeFileSync(path.join(dir, "ic_launcher_background.png"), renderSvg(adaptiveBgSvg, adaptiveSize));
        }

        const anydpiDir = path.join(target, "mipmap-anydpi-v26");
        fs.mkdirSync(anydpiDir, { recursive: true });
        const adaptiveXml = `<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@mipmap/ic_launcher_background" />
    <foreground android:drawable="@mipmap/ic_launcher_foreground" />
</adaptive-icon>
`;
        fs.writeFileSync(path.join(anydpiDir, "ic_launcher.xml"), adaptiveXml);
        fs.writeFileSync(path.join(anydpiDir, "ic_launcher_round.xml"), adaptiveXml);
    }

    const iosDir = "ios/App/App/Assets.xcassets/AppIcon.appiconset";
    if (fs.existsSync(iosDir)) {
        const iosSizes = [
            ["AppIcon-20x20@1x.png", 20],
            ["AppIcon-20x20@2x.png", 40],
            ["AppIcon-20x20@3x.png", 60],
            ["AppIcon-29x29@1x.png", 29],
            ["AppIcon-29x29@2x.png", 58],
            ["AppIcon-29x29@3x.png", 87],
            ["AppIcon-40x40@1x.png", 40],
            ["AppIcon-40x40@2x.png", 80],
            ["AppIcon-40x40@3x.png", 120],
            ["AppIcon-60x60@2x.png", 120],
            ["AppIcon-60x60@3x.png", 180],
            ["AppIcon-76x76@2x.png", 152],
            ["AppIcon-83.5x83.5@2x.png", 167],
            ["AppIcon-1024x1024@1x.png", 1024]
        ];
        for (const [name, sz] of iosSizes) {
            fs.writeFileSync(path.join(iosDir, name), renderSvg(fullIconSvg, sz));
        }
    }

    console.log("Icons generated successfully.");
}

main().catch(console.error);
