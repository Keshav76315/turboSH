// Component ported and enhanced from https://codepen.io/JuanFuentes/pen/eYEeoyE
  
import ASCIIText from './ASCIIText';

<ASCIIText
  text="TurboSH"
  enableWaves={true}
  asciiFontSize={7}
/>


##  2nd component
import ScrollExpand from './ScrollExpand';

<ScrollExpand
  src="/hero.jpg"
  alt="Product hero"
  title="Built to scale"
  scrollHint="Scroll"
  useWindowScroll
>
  <h2>Every pixel, everywhere</h2>
  <p>The frame opens up as you scroll and hands the whole stage to your media.</p>
</ScrollExpand>

<div style={{ height: '520px' }}>
  <ScrollExpand src="/hero.jpg" title="Built to scale" mediaZoom={1.35} />
</div>

### 3rd component : import PixelSwap from './PixelSwap';

<PixelSwap
  firstContent={
    <div className="click-prompt">
      <span>Click me</span>
    </div>
  }
  secondContent={
    <div className="found-message">
      <span>You found me</span>
    </div>
  }
  pixelSize={32}
  gap={0}
  pixelRadius={0}
  pixelSpin={0}
  pixelScale={0.25}
  duration={1000}
  pixelDuration={250}
  pattern="center"
  randomness={0}
  fade
  trigger="click"
/>

### 4th component: import LogoLoop from './LogoLoop';
import { SiReact, SiNextdotjs, SiTypescript, SiTailwindcss } from 'react-icons/si';

const techLogos = [
  { node: <SiReact />, title: "React", href: "https://react.dev" },
  { node: <SiNextdotjs />, title: "Next.js", href: "https://nextjs.org" },
  { node: <SiTypescript />, title: "TypeScript", href: "https://www.typescriptlang.org" },
  { node: <SiTailwindcss />, title: "Tailwind CSS", href: "https://tailwindcss.com" },
];

// Alternative with image sources
const imageLogos = [
  { src: "/logos/company1.png", alt: "Company 1", href: "https://company1.com" },
  { src: "/logos/company2.png", alt: "Company 2", href: "https://company2.com" },
  { src: "/logos/company3.png", alt: "Company 3", href: "https://company3.com" },
];

function App() {
  return (
    <div style={{ height: '200px', position: 'relative', overflow: 'hidden'}}>
      {/* Basic horizontal loop */}
      <LogoLoop
        logos={techLogos}
        speed={120}
        direction="left"
        logoHeight={48}
        gap={40}
        hoverSpeed={0}
        scaleOnHover
        fadeOut
        fadeOutColor="#ffffff"
        ariaLabel="Technology partners"
      />
      
      {/* Vertical loop with deceleration on hover */}
      <LogoLoop
        logos={techLogos}
        speed={80}
        direction="up"
        logoHeight={48}
        gap={40}
        hoverSpeed={20}
        fadeOut
      />
    </div>
  );
}
### 5th component
import CurvedLoop from './CurvedLoop';

// Basic usage
<CurvedLoop marqueeText="Welcome to React Bits ✦" />

// With custom props
<CurvedLoop 
  marqueeText="Be ✦ Creative ✦ With ✦ React ✦ Bits ✦"
  speed={3}
  curveAmount={500}
  direction="right"
  interactive={true}
  className="custom-text-style"
/>

// Non-interactive with slower speed
<CurvedLoop 
  marqueeText="Smooth Curved Animation"
  speed={1}
  curveAmount={300}
  interactive={false}
/>

### 6th compinent :
import DriftWall from './DriftWall';

const items = [
  { image: 'https://picsum.photos/id/1015/600/400', title: 'Peaks', href: 'https://example.com/one' },
  { image: 'https://picsum.photos/id/1025/600/400', title: 'Pup', href: 'https://example.com/two' },
  { image: 'https://picsum.photos/id/1039/600/400', title: 'Falls', href: 'https://example.com/three' },
];

<div style={{ height: 600 }}>
  <DriftWall
    items={items}
    columns={5}
    tileWidth={200}
    tileHeight={132}
    gap={18}
    tilt={16}
    turn={-14}
    perspective={1200}
    depth={120}
    speed={42}
    direction="up"
    variance={0.45}
    parallax={0.6}
    lift={64}
    fade={0.6}
    dim={0.55}
    overlayColor="#060010"
  />
</div>

### 7th componenet : 
import LightRays from './LightRays';

<div style={{ width: '100%', height: '600px', position: 'relative' }}>
  <LightRays
    raysOrigin="top-center"
    raysColor="#00ffff"
    raysSpeed={0.7}
    lightSpread={0.1}
    rayLength={1.2}
    followMouse={true}
    mouseInfluence={0.1}
    noiseAmount={0.1}
    distortion={0.05}
    className="custom-rays"
    fadeDistance={0.8}
/>
</div>
