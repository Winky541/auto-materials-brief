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
    name: `${options.name} · Team Corner`,
    baseY: 0,
  };
  group.position.set(...options.position);
  group.rotation.y = options.rotationY || 0;
  group.scale.setScalar(options.scale || 1);
  scene.add(group);

  const skin = material(options.skin || 0xe4bfa9, 0.72);
  const hairMat = material(options.hair || 0x1d1b1c, 0.78);
  const shirtMat = material(options.shirt || 0xf7f7f2, 0.66);
  const accentMat = material(options.accent || colors.green, 0.62);
  const darkMat = material(0x272322, 0.72);

  const shadow = new THREE.Mesh(new THREE.CircleGeometry(0.32, 28), flatMaterial(0x3a2f24, 0.1));
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.set(0, 0.01, 0);
  shadow.scale.set(1.25, 0.56, 1);
  group.add(shadow);

  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.17, 0.42, 8, 18), shirtMat);
  body.position.set(0, 0.46, 0);
  body.scale.set(options.bodyScale?.[0] || 1, options.bodyScale?.[1] || 1, options.bodyScale?.[2] || 1);
  body.castShadow = true;
  group.add(body);

  const collarLeft = new THREE.Mesh(new THREE.ConeGeometry(0.055, 0.12, 3), material(0xffffff, 0.6));
  collarLeft.position.set(-0.055, 0.63, 0.14);
  collarLeft.rotation.set(0.6, 0.2, -0.68);
  const collarRight = collarLeft.clone();
  collarRight.position.x = 0.055;
  collarRight.rotation.z = 0.68;
  group.add(collarLeft, collarRight);

  if (options.tie) {
    const tie = new THREE.Mesh(new THREE.ConeGeometry(0.045, 0.26, 4), material(options.tie, 0.7));
    tie.position.set(0, 0.47, 0.17);
    tie.rotation.x = Math.PI;
    group.add(tie);
  } else {
    const badge = new THREE.Mesh(new THREE.SphereGeometry(0.025, 10, 8), accentMat);
    badge.scale.set(1, 0.42, 1);
    badge.position.set(0.08, 0.5, 0.17);
    group.add(badge);
  }

  const head = new THREE.Mesh(new THREE.SphereGeometry(0.18, 24, 18), skin);
  head.scale.set(options.faceScale?.[0] || 1, options.faceScale?.[1] || 1, options.faceScale?.[2] || 1);
  head.position.set(0, 0.86, 0);
  head.castShadow = true;
  group.add(head);

  const neck = new THREE.Mesh(new THREE.CylinderGeometry(0.055, 0.06, 0.13, 14), skin);
  neck.position.set(0, 0.69, 0);
  group.add(neck);

  const hairCap = new THREE.Mesh(new THREE.SphereGeometry(0.186, 22, 12), hairMat);
  hairCap.scale.set(options.hairScale?.[0] || 1.04, options.hairScale?.[1] || 0.56, options.hairScale?.[2] || 1.02);
  hairCap.position.set(0, 0.985, -0.008);
  group.add(hairCap);

  if (options.hairStyle === "fringe") {
    [-0.09, -0.03, 0.035, 0.095].forEach((x, index) => {
      const bang = new THREE.Mesh(new THREE.ConeGeometry(0.04, 0.14 - index * 0.008, 3), hairMat);
      bang.position.set(x, 0.91, 0.14);
      bang.rotation.set(0.72, 0, Math.PI + (index - 1.5) * 0.1);
      group.add(bang);
    });
  } else if (options.hairStyle === "short") {
    for (let i = 0; i < 8; i++) {
      const dot = new THREE.Mesh(new THREE.SphereGeometry(0.034, 8, 6), hairMat);
      dot.position.set(-0.14 + i * 0.04, 1.035 + Math.sin(i) * 0.014, 0.07 + Math.cos(i) * 0.015);
      dot.scale.set(1, 0.65, 0.8);
      group.add(dot);
    }
  } else {
    [-0.12, -0.055, 0.055, 0.12].forEach((x, index) => {
      const wave = new THREE.Mesh(new THREE.SphereGeometry(0.075, 14, 10), hairMat);
      wave.scale.set(0.9, 0.6, 0.78);
      wave.position.set(x, 0.985 + (index % 2) * 0.035, 0.1);
      group.add(wave);
    });
    const parted = new THREE.Mesh(new THREE.BoxGeometry(0.018, 0.13, 0.025), material(0x5c4a43, 0.75));
    parted.position.set(0.018, 1.0, 0.17);
    parted.rotation.z = -0.22;
    group.add(parted);
  }

  [-0.062, 0.062].forEach((x) => {
    const eye = new THREE.Mesh(new THREE.SphereGeometry(0.013, 10, 8), darkMat);
    eye.scale.set(1.2, 0.65, 0.55);
    eye.position.set(x, 0.86, 0.17);
    group.add(eye);
  });

  const nose = new THREE.Mesh(new THREE.SphereGeometry(0.014, 8, 6), skin);
  nose.scale.set(0.65, 1.1, 0.8);
  nose.position.set(0, 0.825, 0.184);
  group.add(nose);

  const mouth = new THREE.Mesh(new THREE.BoxGeometry(options.smile ? 0.07 : 0.05, 0.006, 0.01), material(0x9d6d68, 0.72));
  mouth.position.set(0, 0.78, 0.181);
  mouth.rotation.z = options.smile ? 0.02 : 0;
  group.add(mouth);

  [-0.2, 0.2].forEach((x, index) => {
    const arm = new THREE.Mesh(new THREE.CapsuleGeometry(0.035, 0.3, 6, 10), shirtMat);
    arm.position.set(x, 0.48, 0.03);
    arm.rotation.z = index ? -0.38 : 0.38;
    arm.castShadow = true;
    group.add(arm);
  });

  const namePlate = new THREE.Mesh(new THREE.BoxGeometry(0.48, 0.055, 0.08), material(0xf7f1e6, 0.66));
  namePlate.position.set(0, 0.08, 0.24);
  group.add(namePlate);

  addInteractive(group, `team:${options.id}`, `${options.name} · Team Corner`);
  teamGroups.push(group);
  return group;
}

const teamCorner = new THREE.Group();
teamCorner.position.set(4.05, 0.02, -1.55);
teamCorner.rotation.y = -0.48;
scene.add(teamCorner);
const teamRug = new THREE.Mesh(new THREE.CircleGeometry(0.86, 36), flatMaterial(0xc8a45a, 0.16));
teamRug.scale.set(1.5, 0.52, 1);
teamRug.rotation.x = -Math.PI / 2;
teamRug.position.set(0, 0.012, 0.04);
teamCorner.add(teamRug);
const teamMarker = new THREE.Mesh(new THREE.BoxGeometry(1.52, 0.05, 0.07), material(0xd9c6a4, 0.7));
teamMarker.position.set(0.05, 0.05, 0.45);
teamCorner.add(teamMarker);
const teamWallLabel = new THREE.Mesh(new THREE.BoxGeometry(1.05, 0.22, 0.035), material(0xf6f0e7, 0.76));
teamWallLabel.position.set(0.08, 1.42, -0.37);
teamWallLabel.rotation.x = -0.02;
teamCorner.add(teamWallLabel);

createCapsulePerson({
  id: "zhou-qiang",
  name: "周强",
  position: [3.45, 0.02, -1.22],
  rotationY: -0.34,
  scale: 0.72,
  hairStyle: "fringe",
  faceScale: [0.9, 1.12, 0.96],
  bodyScale: [0.9, 1.02, 0.9],
  shirt: 0xf7f7f3,
  accent: colors.green,
});

createCapsulePerson({
  id: "gou-zhi",
  name: "苟智",
  position: [4.02, 0.02, -1.28],
  rotationY: -0.4,
  scale: 0.76,
  hairStyle: "short",
  faceScale: [1.13, 1.02, 1.0],
  bodyScale: [1.1, 1.04, 1],
  shirt: 0x1f2933,
  tie: 0x303766,
  accent: colors.blue,
  smile: true,
});

createCapsulePerson({
  id: "liang-yunqi",
  name: "梁蕴祺",
  position: [4.58, 0.02, -1.22],
  rotationY: -0.46,
  scale: 0.74,
  hairStyle: "parted",
  faceScale: [0.92, 1.08, 0.96],
  bodyScale: [0.95, 1.04, 0.94],
  shirt: 0xf9f9f5,
  accent: colors.clay,
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
