import * as THREE from "https://unpkg.com/three@0.160.0/build/three.module.js";

const container = document.getElementById("auraStudio3d");
const label = document.getElementById("studioObjectLabel");

if (!container) {
  throw new Error("AURA Studio container is missing.");
}

const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const scene = new THREE.Scene();
scene.background = new THREE.Color(0xf7f4ee);

const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
camera.position.set(5.6, 3.4, 7.4);
camera.lookAt(0, 1.35, 0);

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
container.appendChild(renderer.domElement);

const interactive = [];
const outdoorFoliage = [];
let catGroup;
let catBody;
let catHead;
let catTail;
const catEars = [];
const teamGroups = [];
const pointer = new THREE.Vector2();
const raycaster = new THREE.Raycaster();
let hovered = null;

const colors = {
  wall: 0xf4f0e8,
  floor: 0xd8c2a6,
  wood: 0xbfa17a,
  darkWood: 0x8f7656,
  paper: 0xfaf8f1,
  green: 0x6b8e6e,
  clay: 0xc97b63,
  sand: 0xc8a45a,
  violet: 0x8d7ab8,
  blue: 0x4a6fa5,
  graphite: 0x1f2933,
};

function material(color, roughness = 0.62, metalness = 0.02) {
  return new THREE.MeshStandardMaterial({ color, roughness, metalness });
}

function glassMaterial() {
  return new THREE.MeshPhysicalMaterial({
    color: 0xf7fbff,
    roughness: 0.04,
    metalness: 0,
    transmission: 0.52,
    transparent: true,
    opacity: 0.28,
    clearcoat: 1,
    clearcoatRoughness: 0.05,
  });
}

function flatMaterial(color, opacity = 1) {
  return new THREE.MeshBasicMaterial({
    color,
    transparent: opacity < 1,
    opacity,
    side: THREE.DoubleSide,
  });
}

function createSoftBlob(color, x, y, z, scale, opacity = 0.42) {
  const blob = new THREE.Mesh(new THREE.CircleGeometry(0.5, 28), flatMaterial(color, opacity));
  blob.position.set(x, y, z);
  blob.scale.set(scale[0], scale[1], 1);
  return blob;
}

function mesh(geometry, mat, position, rotation = [0, 0, 0], cast = true, receive = true) {
  const item = new THREE.Mesh(geometry, mat);
  item.position.set(...position);
  item.rotation.set(...rotation);
  item.castShadow = cast;
  item.receiveShadow = receive;
  scene.add(item);
  return item;
}

function addInteractive(root, id, name) {
  root.traverse((child) => {
    if (child.isMesh) {
      child.userData.target = id;
      child.userData.name = name;
      interactive.push(child);
    }
  });
}

function createGroup(id, name) {
  const group = new THREE.Group();
  group.userData = { target: id, name, baseY: 0 };
  scene.add(group);
  return group;
}

scene.add(new THREE.HemisphereLight(0xffffff, 0xd8c7b4, 1.35));
const sun = new THREE.DirectionalLight(0xfff5dc, 3.7);
sun.position.set(-3.8, 6.5, 5.2);
sun.castShadow = true;
sun.shadow.mapSize.width = 2048;
sun.shadow.mapSize.height = 2048;
sun.shadow.camera.near = 1;
sun.shadow.camera.far = 18;
sun.shadow.camera.left = -8;
sun.shadow.camera.right = 8;
sun.shadow.camera.top = 8;
sun.shadow.camera.bottom = -8;
scene.add(sun);
scene.add(new THREE.AmbientLight(0xffffff, 0.34));

mesh(new THREE.PlaneGeometry(11, 7), material(colors.wall, 0.88), [0, 2.6, -3.05], [0, 0, 0], false, true);
mesh(new THREE.PlaneGeometry(11, 7), material(colors.floor, 0.74), [0, -0.02, 0.1], [-Math.PI / 2, 0, 0], false, true);
mesh(new THREE.BoxGeometry(7.8, 0.28, 2.6), material(colors.wood, 0.58), [0.45, 0.86, 0.55]);
mesh(new THREE.BoxGeometry(0.26, 1.25, 0.26), material(colors.darkWood, 0.7), [-3.15, 0.22, -0.36]);
mesh(new THREE.BoxGeometry(0.26, 1.25, 0.26), material(colors.darkWood, 0.7), [3.9, 0.22, -0.36]);
mesh(new THREE.BoxGeometry(0.26, 1.25, 0.26), material(colors.darkWood, 0.7), [-3.15, 0.22, 1.36]);
mesh(new THREE.BoxGeometry(0.26, 1.25, 0.26), material(colors.darkWood, 0.7), [3.9, 0.22, 1.36]);

const windowGroup = createGroup("future-signals", "Window · Future Signals");
windowGroup.position.set(2.45, 2.9, -2.92);
const outsideSky = new THREE.Mesh(new THREE.PlaneGeometry(2.18, 1.42), flatMaterial(0xbfd8df, 1));
outsideSky.position.z = -0.085;
windowGroup.add(outsideSky);
const skyGlow = createSoftBlob(0xf7f0d7, 0.62, 0.43, -0.079, [0.55, 0.32], 0.34);
windowGroup.add(skyGlow);
const distantHills = new THREE.Mesh(new THREE.PlaneGeometry(2.18, 0.32), flatMaterial(0x9fb49b, 0.42));
distantHills.position.set(0, -0.22, -0.081);
windowGroup.add(distantHills);
const outsideGround = new THREE.Mesh(new THREE.PlaneGeometry(2.18, 0.46), flatMaterial(0x8da877, 1));
outsideGround.position.set(0, -0.48, -0.08);
windowGroup.add(outsideGround);
[-0.9, -0.48, 0.05, 0.58, 0.96].forEach((x, index) => {
  const farCrown = createSoftBlob(index % 2 ? 0x5f815d : 0x78996d, x, -0.18 + (index % 2) * 0.035, -0.074 - index * 0.002, [0.34, 0.22], 0.46);
  farCrown.userData.wave = index * 0.7;
  farCrown.userData.baseScale = farCrown.scale.clone();
  outdoorFoliage.push(farCrown);
  windowGroup.add(farCrown);
});
[-0.62, -0.18, 0.38, 0.78].forEach((x, index) => {
  const tree = new THREE.Group();
  tree.position.set(x, -0.38 + (index % 2) * 0.04, -0.055 - index * 0.004);
  const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.022, 0.032, 0.48, 10), flatMaterial(0x80664a, 0.9));
  trunk.position.y = 0.08;
  const crown = new THREE.Mesh(new THREE.SphereGeometry(0.22 + index * 0.015, 18, 12), flatMaterial(index % 2 ? 0x6f9367 : 0x557d5b, 0.92));
  crown.scale.set(1.05, 1.22, 0.72);
  crown.position.y = 0.39;
  crown.userData.wave = index;
  crown.userData.baseScale = crown.scale.clone();
  outdoorFoliage.push(crown);
  tree.add(trunk, crown);
  windowGroup.add(tree);
});
const distantTrees = new THREE.Mesh(new THREE.PlaneGeometry(2.0, 0.28), flatMaterial(0x6f8f6c, 0.36));
distantTrees.position.set(0.04, -0.1, -0.09);
windowGroup.add(distantTrees);
const glass = new THREE.Mesh(new THREE.BoxGeometry(2.3, 1.55, 0.045), glassMaterial());
windowGroup.add(glass);
const glassHighlight = new THREE.Mesh(new THREE.PlaneGeometry(0.16, 1.42), flatMaterial(0xffffff, 0.18));
glassHighlight.position.set(-0.48, 0.02, 0.035);
glassHighlight.rotation.z = -0.22;
windowGroup.add(glassHighlight);
const windowSill = new THREE.Mesh(new THREE.BoxGeometry(2.7, 0.12, 0.38), material(0xf3efe7, 0.62));
windowSill.position.set(0, -0.93, 0.12);
windowSill.castShadow = true;
windowSill.receiveShadow = true;
windowGroup.add(windowSill);
const topFrame = new THREE.Mesh(new THREE.BoxGeometry(2.48, 0.08, 0.14), material(0xffffff, 0.45));
topFrame.position.y = 0.8;
windowGroup.add(topFrame);
const frameH = new THREE.Mesh(new THREE.BoxGeometry(2.48, 0.08, 0.14), material(0xffffff, 0.45));
frameH.position.y = -0.8;
windowGroup.add(frameH);
const frameV1 = new THREE.Mesh(new THREE.BoxGeometry(0.08, 1.7, 0.14), material(0xffffff, 0.45));
const frameV2 = frameV1.clone();
frameV1.position.x = -1.22;
frameV2.position.x = 1.22;
windowGroup.add(frameV1, frameV2);
const centerV = new THREE.Mesh(new THREE.BoxGeometry(0.055, 1.6, 0.15), material(0xffffff, 0.45));
windowGroup.add(centerV);
addInteractive(windowGroup, "future-signals", "Window · Future Signals");

const sunPatch = new THREE.Mesh(new THREE.PlaneGeometry(2.25, 1.18), flatMaterial(0xf5e8c7, 0.18));
sunPatch.position.set(1.9, 0.012, -0.1);
sunPatch.rotation.set(-Math.PI / 2, 0, -0.28);
scene.add(sunPatch);
const windowLight = new THREE.RectAreaLight(0xfff0d0, 2.6, 2.2, 1.35);
windowLight.position.set(2.45, 2.65, -2.45);
windowLight.lookAt(0.6, 1.1, 0.8);
scene.add(windowLight);

const shelfGroup = createGroup("opportunity-graph", "Bookshelf · Material Opportunity Graph");
shelfGroup.position.set(-3.35, 2.05, -2.75);
shelfGroup.add(new THREE.Mesh(new THREE.BoxGeometry(1.8, 0.12, 0.42), material(colors.darkWood, 0.7)));
shelfGroup.children[0].position.y = -0.7;
shelfGroup.add(new THREE.Mesh(new THREE.BoxGeometry(1.8, 0.12, 0.42), material(colors.darkWood, 0.7)));
shelfGroup.children[1].position.y = 0.2;
[colors.green, colors.sand, colors.clay, colors.blue, colors.violet, colors.green].forEach((c, i) => {
  const book = new THREE.Mesh(new THREE.BoxGeometry(0.18, 0.82 + (i % 3) * 0.13, 0.34), material(c, 0.58));
  book.position.set(-0.66 + i * 0.25, -0.26 + book.geometry.parameters.height / 2 - 0.42, 0.03);
  book.rotation.z = (i - 2) * 0.025;
  shelfGroup.add(book);
});
addInteractive(shelfGroup, "opportunity-graph", "Bookshelf · Material Opportunity Graph");

const notebookGroup = createGroup("key-insight", "Notebook · Today's Key Insight");
notebookGroup.position.set(-0.98, 1.16, 0.66);
notebookGroup.rotation.y = -0.26;
notebookGroup.add(new THREE.Mesh(new THREE.BoxGeometry(1.35, 0.08, 0.92), material(colors.paper, 0.7)));
const binding = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.1, 0.96), material(colors.green, 0.56));
binding.position.x = -0.68;
notebookGroup.add(binding);
for (let i = 0; i < 4; i++) {
  const line = new THREE.Mesh(new THREE.BoxGeometry(0.76, 0.012, 0.012), material(0xb9c4b4, 0.7));
  line.position.set(0.08, 0.055, -0.25 + i * 0.16);
  notebookGroup.add(line);
}
addInteractive(notebookGroup, "key-insight", "Notebook · Today's Key Insight");

const paletteGroup = createGroup("suggested-actions", "Palette · Suggested Actions");
paletteGroup.position.set(1.05, 1.18, 0.76);
paletteGroup.rotation.y = 0.34;
const palette = new THREE.Mesh(new THREE.CylinderGeometry(0.56, 0.62, 0.08, 48), material(0xf8f1e4, 0.64));
palette.scale.x = 1.25;
paletteGroup.add(palette);
[[colors.green, -0.26, 0.18], [colors.clay, 0.18, 0.22], [colors.sand, 0.34, -0.1], [colors.violet, -0.04, -0.24], [colors.blue, -0.36, -0.08]].forEach(([c, x, z]) => {
  const paint = new THREE.Mesh(new THREE.SphereGeometry(0.105, 20, 12), material(c, 0.38));
  paint.scale.y = 0.28;
  paint.position.set(x, 0.07, z);
  paletteGroup.add(paint);
});
addInteractive(paletteGroup, "suggested-actions", "Palette · Suggested Actions");

const archiveGroup = createGroup("archives", "Archive Box · Archive");
archiveGroup.position.set(2.75, 1.22, 0.58);
archiveGroup.rotation.y = -0.18;
archiveGroup.add(new THREE.Mesh(new THREE.BoxGeometry(0.92, 0.46, 0.72), material(0xd2b487, 0.68)));
const lid = new THREE.Mesh(new THREE.BoxGeometry(1.02, 0.12, 0.82), material(0xc49f68, 0.66));
lid.position.y = 0.3;
lid.userData.isLid = true;
archiveGroup.add(lid);
addInteractive(archiveGroup, "archives", "Archive Box · Archive");

catGroup = new THREE.Group();
catGroup.userData = { target: "insights", name: "Cat · Weekly Insights", baseY: 0 };
catGroup.position.set(-1.62, 0.03, 2.05);
catGroup.rotation.y = -0.18;
catGroup.scale.setScalar(1.22);
scene.add(catGroup);
const catFur = material(0xb8afa3, 0.82);
const catWarmFur = material(0xd8cbb9, 0.82);
const catDark = material(0x4b423b, 0.76);
catBody = new THREE.Mesh(new THREE.SphereGeometry(0.34, 24, 16), catFur);
catBody.scale.set(1.62, 0.46, 0.72);
catBody.position.set(0.12, 0.2, 0);
catBody.castShadow = true;
catBody.receiveShadow = true;
catGroup.add(catBody);
catHead = new THREE.Mesh(new THREE.SphereGeometry(0.18, 20, 14), catWarmFur);
catHead.scale.set(1.16, 0.9, 0.96);
catHead.position.set(-0.48, 0.26, 0.06);
catHead.userData.baseY = catHead.position.y;
catHead.castShadow = true;
catGroup.add(catHead);
[-0.57, -0.39].forEach((x, index) => {
  const ear = new THREE.Mesh(new THREE.ConeGeometry(0.075, 0.16, 3), catFur);
  ear.position.set(x, 0.41, 0.055 + (index ? 0.075 : -0.075));
  ear.rotation.set(index ? 0.2 : -0.2, 0, Math.PI);
  ear.userData.baseRotation = ear.rotation.clone();
  ear.castShadow = true;
  catEars.push(ear);
  catGroup.add(ear);
});
[-0.05, 0.075].forEach((z) => {
  const eye = new THREE.Mesh(new THREE.BoxGeometry(0.055, 0.007, 0.012), catDark);
  eye.position.set(-0.58, 0.27, z);
  eye.rotation.x = z > 0 ? 0.18 : -0.18;
  catGroup.add(eye);
});
const nose = new THREE.Mesh(new THREE.SphereGeometry(0.024, 10, 8), material(0xa98379, 0.72));
nose.scale.set(0.8, 0.62, 0.5);
nose.position.set(-0.66, 0.23, 0.02);
catGroup.add(nose);
[-1, 1].forEach((side) => {
  for (let i = 0; i < 3; i++) {
    const whisker = new THREE.Mesh(new THREE.CylinderGeometry(0.0035, 0.0035, 0.19, 6), catDark);
    whisker.position.set(-0.64, 0.22 - i * 0.026, side * 0.06);
    whisker.rotation.set(Math.PI / 2, side * 0.62, Math.PI / 2 + (i - 1) * 0.14);
    catGroup.add(whisker);
  }
});
catTail = new THREE.Mesh(new THREE.TorusGeometry(0.23, 0.033, 12, 34, Math.PI * 1.22), catFur);
catTail.position.set(0.58, 0.22, -0.02);
catTail.rotation.set(1.2, 0.12, -0.34);
catTail.castShadow = true;
catGroup.add(catTail);
[-0.18, 0.16].forEach((x) => {
  const paw = new THREE.Mesh(new THREE.SphereGeometry(0.065, 12, 8), catWarmFur);
  paw.scale.set(1.18, 0.28, 0.7);
  paw.position.set(x, 0.02, 0.22);
  paw.castShadow = true;
  catGroup.add(paw);
});
const catShadow = new THREE.Mesh(new THREE.CircleGeometry(0.48, 32), flatMaterial(0x3a2f24, 0.11));
catShadow.position.set(0.08, -0.055, 0.02);
catShadow.scale.set(1.5, 0.54, 1);
catShadow.rotation.x = -Math.PI / 2;
catGroup.add(catShadow);
addInteractive(catGroup, "insights", "Cat · Weekly Insights");

function createCapsulePerson(options) {
  const group = new THREE.Group();
  group.userData = {
    target: `team:${options.id}`,
    name: options.name,
    baseY: 0,
  };
  group.position.set(...options.position);
  group.rotation.y = options.rotationY || 0;
  group.scale.setScalar(options.scale || 1);
  scene.add(group);

  const portraitCanvas = document.createElement("canvas");
  portraitCanvas.width = 384;
  portraitCanvas.height = 520;
  const ctx = portraitCanvas.getContext("2d");
  const portrait = options.portrait || {};
  const skinColor = portrait.skin || "#e7c1ad";
  const hairColor = portrait.hair || "#191715";
  const shirtColor = portrait.shirt || "#f7f7f2";
  const accentColor = portrait.accent || "#6b8e6e";
  const suitColor = portrait.suit || null;

  ctx.clearRect(0, 0, portraitCanvas.width, portraitCanvas.height);
  ctx.save();
  ctx.translate(192, 260);
  ctx.shadowColor = "rgba(31, 41, 51, 0.08)";
  ctx.shadowBlur = 18;
  ctx.shadowOffsetY = 10;
  ctx.fillStyle = "rgba(255, 252, 244, 0.88)";
  ctx.beginPath();
  ctx.roundRect(-118, -178, 236, 338, 60);
  ctx.fill();
  ctx.restore();

  function ellipse(fill, x, y, rx, ry) {
    ctx.fillStyle = fill;
    ctx.beginPath();
    ctx.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2);
    ctx.fill();
  }

  function roundedRect(fill, x, y, w, h, r) {
    ctx.fillStyle = fill;
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, r);
    ctx.fill();
  }

  function colorNumber(value, fallback) {
    if (typeof value === "number") return value;
    const parsed = Number.parseInt(String(value || "").replace("#", ""), 16);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  roundedRect(suitColor || shirtColor, 104, 318, 176, 148, 52);
  if (suitColor) {
    ctx.fillStyle = "#f7f6f1";
    ctx.beginPath();
    ctx.moveTo(142, 322);
    ctx.lineTo(192, 410);
    ctx.lineTo(242, 322);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = portrait.tie || "#303766";
    ctx.beginPath();
    ctx.moveTo(184, 350);
    ctx.lineTo(200, 350);
    ctx.lineTo(208, 430);
    ctx.lineTo(176, 430);
    ctx.closePath();
    ctx.fill();
  } else {
    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.moveTo(140, 324);
    ctx.lineTo(190, 382);
    ctx.lineTo(244, 324);
    ctx.lineTo(238, 360);
    ctx.lineTo(190, 402);
    ctx.lineTo(146, 360);
    ctx.closePath();
    ctx.fill();
    ellipse(accentColor, 192, 412, 9, 5);
  }

  ellipse(skinColor, 192, 246, portrait.faceRx || 76, portrait.faceRy || 92);
  ellipse("rgba(196, 135, 114, 0.18)", 154, 268, 18, 8);
  ellipse("rgba(196, 135, 114, 0.18)", 230, 268, 18, 8);

  ctx.fillStyle = hairColor;
  if (portrait.style === "short") {
    ellipse(hairColor, 192, 166, 88, 46);
    roundedRect(hairColor, 115, 174, 154, 48, 22);
    for (let i = 0; i < 9; i++) ellipse(hairColor, 118 + i * 18, 194 + Math.sin(i) * 4, 16, 18);
  } else if (portrait.style === "parted") {
    ellipse(hairColor, 164, 168, 58, 44);
    ellipse(hairColor, 218, 164, 62, 48);
    roundedRect(hairColor, 112, 176, 160, 54, 28);
    ctx.fillStyle = "#6d554c";
    roundedRect(ctx.fillStyle, 190, 154, 10, 80, 5);
    ellipse(hairColor, 214, 212, 28, 46);
  } else {
    ellipse(hairColor, 192, 168, 82, 46);
    roundedRect(hairColor, 118, 178, 148, 50, 22);
    for (let i = 0; i < 7; i++) {
      ctx.fillStyle = hairColor;
      ctx.beginPath();
      const x = 132 + i * 19;
      ctx.moveTo(x, 205);
      ctx.lineTo(x + 18, 205);
      ctx.lineTo(x + 8, 238 + (i % 2) * 8);
      ctx.closePath();
      ctx.fill();
    }
  }

  ctx.strokeStyle = "rgba(31, 41, 51, 0.48)";
  ctx.lineWidth = 6;
  ctx.lineCap = "round";
  const browOffset = portrait.style === "short" ? 3 : 0;
  ctx.beginPath();
  ctx.moveTo(147, 238 - browOffset);
  ctx.lineTo(174, 234 - browOffset);
  ctx.moveTo(210, 234 - browOffset);
  ctx.lineTo(238, 238 - browOffset);
  ctx.stroke();

  ellipse("#1f2933", 160, 255, 7, portrait.style === "short" ? 5 : 6);
  ellipse("#1f2933", 224, 255, 7, portrait.style === "short" ? 5 : 6);
  ctx.strokeStyle = "rgba(126, 82, 68, 0.42)";
  ctx.lineWidth = 4;
  ctx.beginPath();
  ctx.moveTo(193, 260);
  ctx.quadraticCurveTo(185, 282, 196, 291);
  ctx.stroke();
  ctx.strokeStyle = portrait.smile ? "#9a6761" : "#8e625d";
  ctx.lineWidth = 5;
  ctx.beginPath();
  if (portrait.smile) {
    ctx.moveTo(168, 308);
    ctx.quadraticCurveTo(192, 320, 216, 308);
  } else {
    ctx.moveTo(174, 310);
    ctx.quadraticCurveTo(192, 314, 210, 310);
  }
  ctx.stroke();
  ctx.clearRect(0, 326, 384, 194);

  const portraitChairMat = material(0xb99b70, 0.72);
  const portraitChairBack = new THREE.Mesh(new THREE.BoxGeometry(0.68, 0.54, 0.08), portraitChairMat);
  portraitChairBack.position.set(0, 0.55, -0.07);
  portraitChairBack.castShadow = true;
  group.add(portraitChairBack);
  const portraitSeat = new THREE.Mesh(new THREE.CylinderGeometry(0.32, 0.34, 0.08, 28), portraitChairMat);
  portraitSeat.position.set(0, 0.25, 0.03);
  portraitSeat.scale.set(1.08, 1, 0.62);
  portraitSeat.castShadow = true;
  group.add(portraitSeat);

  const bodyColor = colorNumber(suitColor || shirtColor, 0xf7f7f2);
  const bodyMat = material(bodyColor, 0.68);
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.19, 0.5, 10, 18), bodyMat);
  body.position.set(0, 0.48, 0.045);
  body.scale.set(portrait.style === "short" ? 1.08 : 0.96, 1.04, 0.7);
  body.castShadow = true;
  group.add(body);

  const collarMat = material(0xffffff, 0.62);
  const collarLeft = new THREE.Mesh(new THREE.ConeGeometry(0.07, 0.14, 3), collarMat);
  collarLeft.position.set(-0.075, 0.64, 0.18);
  collarLeft.rotation.set(0.6, 0.2, -0.7);
  const collarRight = collarLeft.clone();
  collarRight.position.x = 0.075;
  collarRight.rotation.z = 0.7;
  group.add(collarLeft, collarRight);

  if (suitColor) {
    const tie = new THREE.Mesh(new THREE.ConeGeometry(0.045, 0.24, 4), material(colorNumber(portrait.tie, 0x303766), 0.7));
    tie.position.set(0, 0.49, 0.19);
    tie.rotation.x = Math.PI;
    group.add(tie);
  } else {
    const badge = new THREE.Mesh(new THREE.SphereGeometry(0.025, 10, 8), material(colorNumber(accentColor, colors.green), 0.62));
    badge.scale.set(1, 0.42, 1);
    badge.position.set(0.08, 0.49, 0.2);
    group.add(badge);
  }

  [-0.23, 0.23].forEach((x, index) => {
    const arm = new THREE.Mesh(new THREE.CapsuleGeometry(0.038, 0.32, 6, 12), bodyMat);
    arm.position.set(x, 0.48, 0.065);
    arm.rotation.z = index ? -0.36 : 0.36;
    arm.castShadow = true;
    group.add(arm);
  });

  const texture = new THREE.CanvasTexture(portraitCanvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const portraitMat = new THREE.MeshBasicMaterial({
    map: texture,
    transparent: true,
    side: THREE.DoubleSide,
  });
  const portraitPlane = new THREE.Mesh(new THREE.PlaneGeometry(0.86, 1.16), portraitMat);
  portraitPlane.position.set(0, 0.83, 0.23);
  portraitPlane.castShadow = true;
  group.add(portraitPlane);
  const portraitShadow = new THREE.Mesh(new THREE.CircleGeometry(0.38, 30), flatMaterial(0x3a2f24, 0.1));
  portraitShadow.rotation.x = -Math.PI / 2;
  portraitShadow.position.set(0, 0.01, 0.03);
  portraitShadow.scale.set(1.3, 0.58, 1);
  group.add(portraitShadow);

  addInteractive(group, `team:${options.id}`, options.name);
  teamGroups.push(group);
  return group;

}

const teamCorner = new THREE.Group();
teamCorner.position.set(1.55, 0.02, 1.94);
teamCorner.rotation.y = 0.02;
scene.add(teamCorner);
const teamRug = new THREE.Mesh(new THREE.CircleGeometry(0.86, 36), flatMaterial(0xc8a45a, 0.16));
teamRug.scale.set(1.7, 0.58, 1);
teamRug.rotation.x = -Math.PI / 2;
teamRug.position.set(0, 0.012, 0.04);
teamCorner.add(teamRug);
const teamMarker = new THREE.Mesh(new THREE.BoxGeometry(1.52, 0.05, 0.07), material(0xd9c6a4, 0.7));
teamMarker.position.set(0.05, 0.05, 0.34);
teamCorner.add(teamMarker);
const teamWallLabel = new THREE.Mesh(new THREE.BoxGeometry(1.05, 0.22, 0.035), material(0xf6f0e7, 0.76));
teamWallLabel.position.set(0.08, 0.42, -0.37);
teamWallLabel.rotation.x = -0.02;
teamCorner.add(teamWallLabel);

createCapsulePerson({
  id: "zhou-qiang",
  name: "周强",
  position: [0.82, 0.02, 1.92],
  rotationY: 0.16,
  scale: 1.02,
  portrait: {
    style: "fringe",
    skin: "#e3baa5",
    hair: "#181615",
    shirt: "#f7f7f2",
    accent: "#6b8e6e",
    faceRx: 70,
    faceRy: 94,
  },
});

createCapsulePerson({
  id: "gou-zhi",
  name: "苟智",
  position: [1.55, 0.02, 1.96],
  rotationY: 0.04,
  scale: 1.06,
  portrait: {
    style: "short",
    skin: "#e9c2b2",
    hair: "#151414",
    shirt: "#f7f6f1",
    suit: "#1f2933",
    tie: "#303766",
    accent: "#4a6fa5",
    faceRx: 84,
    faceRy: 88,
    smile: true,
  },
});

createCapsulePerson({
  id: "liang-yunqi",
  name: "梁蕴祺",
  position: [2.3, 0.02, 1.92],
  rotationY: -0.06,
  scale: 1.03,
  portrait: {
    style: "parted",
    skin: "#e5b9a5",
    hair: "#191514",
    shirt: "#f9f9f5",
    accent: "#c97b63",
    faceRx: 72,
    faceRy: 92,
  },
});

const objectGroups = [windowGroup, shelfGroup, notebookGroup, paletteGroup, archiveGroup, catGroup, ...teamGroups];
objectGroups.forEach((group) => {
  group.userData.baseY = group.position.y;
});

function resize() {
  const rect = container.getBoundingClientRect();
  renderer.setSize(rect.width, rect.height, false);
  camera.aspect = rect.width / Math.max(rect.height, 1);
  camera.updateProjectionMatrix();
}

function pick(event, click = false) {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hit = raycaster.intersectObjects(interactive, false)[0]?.object;
  const group = hit ? objectGroups.find((item) => {
    let cursor = hit;
    while (cursor) {
      if (cursor === item) return true;
      cursor = cursor.parent;
    }
    return false;
  }) : null;
  if (click && group?.userData.target) {
    const target = group.userData.target;
    if (String(target).startsWith("team:")) {
      window.AURAStudioOpenProfile?.(String(target).slice(5));
    } else {
      window.AURAStudioOpenPanel?.(target);
    }
  }
  if (hovered !== group) {
    hovered = group || null;
    renderer.domElement.style.cursor = hovered ? "pointer" : "default";
    label.textContent = hovered?.userData.name || "";
    label.classList.toggle("is-visible", Boolean(hovered));
  }
}

renderer.domElement.addEventListener("pointermove", (event) => pick(event));
renderer.domElement.addEventListener("click", (event) => pick(event, true));
window.addEventListener("resize", resize);
resize();
container.classList.add("is-ready");
document.body.classList.add("studio-3d-ready");

function animate(time) {
  const t = time * 0.001;
  if (!prefersReducedMotion) {
    objectGroups.forEach((group, index) => {
      const lift = group === hovered ? 0.08 : 0;
      group.position.y += (group.userData.baseY + lift - group.position.y) * 0.1;
      group.rotation.z = Math.sin(t * 0.55 + index) * 0.006;
    });
    const archiveLid = archiveGroup.children.find((child) => child.userData.isLid);
    if (archiveLid) {
      archiveLid.rotation.x += ((hovered === archiveGroup ? -0.22 : 0) - archiveLid.rotation.x) * 0.12;
    }
    outdoorFoliage.forEach((leaf, index) => {
      leaf.rotation.z = Math.sin(t * 0.85 + leaf.userData.wave) * 0.018;
      const base = leaf.userData.baseScale;
      const pulse = 1 + Math.sin(t * 0.6 + index) * 0.012;
      leaf.scale.set(base.x * pulse, base.y, base.z);
    });
  }
  if (catBody && catHead && catTail) {
    const breath = Math.sin(t * 1.45) * 0.022;
    const sleepyTwitch = Math.max(0, Math.sin(t * 2.65 - 0.7)) ** 5;
    const earTwitch = sleepyTwitch * 0.62 + (hovered === catGroup ? 0.28 : 0);
    catBody.scale.set(1.62 + breath * 0.42, 0.46 + breath, 0.72);
    catHead.position.y = catHead.userData.baseY + Math.sin(t * 1.15 + 0.4) * 0.01;
    catTail.rotation.z = -0.34 + Math.sin(t * 0.95) * 0.07;
    catTail.rotation.y = 0.12 + Math.sin(t * 0.7) * 0.035;
    catEars.forEach((ear, index) => {
      const base = ear.userData.baseRotation;
      ear.rotation.set(
        base.x + earTwitch * (index ? 0.18 : -0.16),
        base.y + Math.sin(t * 4.2 + index) * 0.025,
        base.z + earTwitch * (index ? -0.26 : 0.24)
      );
    });
  }
  renderer.render(scene, camera);
  requestAnimationFrame(animate);
}

requestAnimationFrame(animate);
