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
windowGroup.add(new THREE.Mesh(new THREE.BoxGeometry(2.3, 1.55, 0.08), material(0xeaf3f1, 0.2, 0.0)));
windowGroup.add(new THREE.Mesh(new THREE.BoxGeometry(2.48, 0.08, 0.14), material(0xffffff, 0.45)));
windowGroup.children[1].position.y = 0.8;
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

const objectGroups = [windowGroup, shelfGroup, notebookGroup, paletteGroup, archiveGroup];
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
  const group = hit ? objectGroups.find((item) => item.children.includes(hit)) : null;
  if (click && group?.userData.target) {
    window.AURAStudioOpenPanel?.(group.userData.target);
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
  }
  renderer.render(scene, camera);
  requestAnimationFrame(animate);
}

requestAnimationFrame(animate);
