// ══════════════════════════════════════════════════════════════════════════════
// Aero Piston Engine Digital Twin - 3D Engine Visualizer
// ══════════════════════════════════════════════════════════════════════════════
//
// Interactive 3D visualization of a 4-cylinder horizontally-opposed aero engine.
// Features:
// - Procedural geometry for crankcase, cylinders, pistons, crankshaft
// - Dynamic RPM-linked animation
// - Custom GLSL shader for CHT heatmap
// - Camera presets and orbit controls
// - Exploded view toggle
//
// ══════════════════════════════════════════════════════════════════════════════

import { useRef, useEffect, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { OrbitControls, PerspectiveCamera, Environment } from '@react-three/drei';
import * as THREE from 'three';
import { useTelemetry } from '../../context/TelemetryContext';
import { createCHTShaderMaterial, type CHTShaderUniforms } from '../../shaders/cht_heatmap';
import { RotateCcw, Layers, Camera } from 'lucide-react';
import clsx from 'clsx';

// ══════════════════════════════════════════════════════════════════════════════
// Types
// ══════════════════════════════════════════════════════════════════════════════

interface CameraPreset {
  name: string;
  position: [number, number, number];
  target: [number, number, number];
}

interface Engine3DViewProps {
  className?: string;
  showControls?: boolean;
}

// ══════════════════════════════════════════════════════════════════════════════
// Constants
// ══════════════════════════════════════════════════════════════════════════════

const CAMERA_PRESETS: CameraPreset[] = [
  { name: 'Overview', position: [8, 5, 8], target: [0, 0, 0] },
  { name: 'Bank A (Cyl 1 & 3)', position: [6, 2, 0], target: [0, 0, 0] },
  { name: 'Bank B (Cyl 2 & 4)', position: [-6, 2, 0], target: [0, 0, 0] },
  { name: 'Top View', position: [0, 10, 0.1], target: [0, 0, 0] },
];

// Engine dimensions (normalized)
const ENGINE = {
  crankcaseRadius: 0.8,
  crankcaseLength: 2.5,
  cylinderRadius: 0.35,
  cylinderLength: 1.2,
  pistonRadius: 0.3,
  pistonHeight: 0.4,
  crankRadius: 0.4,
  rodLength: 1.0,
  cylinderSpacing: 0.7,
};

// ══════════════════════════════════════════════════════════════════════════════
// Engine Scene Component
// ══════════════════════════════════════════════════════════════════════════════

interface EngineSceneProps {
  explodedView: number;
}

function EngineScene({ explodedView }: EngineSceneProps) {
  const { currentFrame } = useTelemetry();
  
  // Refs for animated parts
  const crankshaftRef = useRef<THREE.Group>(null);
  const pistonsRef = useRef<THREE.Group[]>([]);
  const cylinderHeadsRef = useRef<THREE.Mesh[]>([]);
  
  // CHT shader materials for each cylinder
  const chtMaterials = useRef<CHTShaderUniforms[]>([]);
  
  // Calculate RPM-based animation
  const rpm = currentFrame?.rpm ?? 0;
  const cht = currentFrame?.cht ?? [180, 178, 182, 179];
  
  // Initialize shader materials
  useEffect(() => {
    chtMaterials.current = cylinderHeadsRef.current.map(() => {
      const material = createCHTShaderMaterial();
      return material.uniforms as unknown as CHTShaderUniforms;
    });
  }, []);
  
  // Update CHT uniforms
  useEffect(() => {
    cht.forEach((temp, i) => {
      if (chtMaterials.current[i]) {
        chtMaterials.current[i].u_cht.value = temp;
      }
    });
  }, [cht]);
  
  // Animation loop
  useFrame((state, delta) => {
    const time = state.clock.getElapsedTime();
    
    // Update shader time uniform
    chtMaterials.current.forEach((uniforms) => {
      if (uniforms?.u_time) {
        uniforms.u_time.value = time;
      }
    });
    
    // Crankshaft rotation (degrees per second based on RPM)
    if (crankshaftRef.current) {
      const degreesPerSecond = (rpm / 60) * 360;
      crankshaftRef.current.rotation.z += (degreesPerSecond * delta * Math.PI) / 180;
    }
    
    // Piston reciprocation
    const crankAngle = crankshaftRef.current?.rotation.z ?? 0;
    
    pistonsRef.current.forEach((pistonGroup, i) => {
      if (!pistonGroup) return;
      
      // Phase offset for 4-cylinder boxer (0°, 180°, 180°, 0° firing order)
      const phaseOffsets = [0, Math.PI, Math.PI, 0];
      const angle = crankAngle + phaseOffsets[i];
      
      // Piston displacement from crank-slider kinematics
      const crankRadius = ENGINE.crankRadius;
      const rodLength = ENGINE.rodLength;
      
      // x = r*cos(θ) + sqrt(l² - r²*sin²(θ))
      const sinAngle = Math.sin(angle);
      const cosAngle = Math.cos(angle);
      const displacement = crankRadius * cosAngle + 
        Math.sqrt(rodLength * rodLength - crankRadius * crankRadius * sinAngle * sinAngle);
      
      // Normalize to piston travel range
      const maxTravel = crankRadius + rodLength;
      const minTravel = rodLength - crankRadius;
      const normalizedDisplacement = (displacement - minTravel) / (maxTravel - minTravel);
      
      // Apply to piston (vertical movement)
      pistonGroup.position.y = (normalizedDisplacement - 0.5) * ENGINE.pistonHeight * 2;
    });
  });
  
  // Exploded view offsets
  const getExplodedOffset = (component: string): [number, number, number] => {
    const e = explodedView;
    switch (component) {
      case 'cylinderLeft':
        return [-e * 1.5, 0, 0];
      case 'cylinderRight':
        return [e * 1.5, 0, 0];
      case 'cylinderHeadLeft':
        return [-e * 2.5, 0, 0];
      case 'cylinderHeadRight':
        return [e * 2.5, 0, 0];
      case 'crankcase':
        return [0, 0, 0];
      case 'crankshaft':
        return [0, -e * 1.0, 0];
      case 'exhaustLeft':
        return [-e * 2.0, e * 0.5, 0];
      case 'exhaustRight':
        return [e * 2.0, e * 0.5, 0];
      default:
        return [0, 0, 0];
    }
  };
  
  return (
    <group>
      {/* ─── Crankcase ─── */}
      <group position={getExplodedOffset('crankcase')}>
        <mesh>
          <cylinderGeometry args={[ENGINE.crankcaseRadius, ENGINE.crankcaseRadius, ENGINE.crankcaseLength, 32]} />
          <meshStandardMaterial 
            color="#4a5568" 
            metalness={0.8} 
            roughness={0.3}
          />
        </mesh>
        {/* Crankcase end caps */}
        <mesh position={[0, ENGINE.crankcaseLength / 2, 0]}>
          <cylinderGeometry args={[ENGINE.crankcaseRadius * 1.1, ENGINE.crankcaseRadius * 1.1, 0.1, 32]} />
          <meshStandardMaterial color="#2d3748" metalness={0.9} roughness={0.2} />
        </mesh>
        <mesh position={[0, -ENGINE.crankcaseLength / 2, 0]}>
          <cylinderGeometry args={[ENGINE.crankcaseRadius * 1.1, ENGINE.crankcaseRadius * 1.1, 0.1, 32]} />
          <meshStandardMaterial color="#2d3748" metalness={0.9} roughness={0.2} />
        </mesh>
      </group>
      
      {/* ─── Crankshaft ─── */}
      <group ref={crankshaftRef} position={getExplodedOffset('crankshaft')}>
        {/* Main shaft */}
        <mesh rotation={[0, 0, Math.PI / 2]}>
          <cylinderGeometry args={[0.12, 0.12, ENGINE.crankcaseLength + 0.5, 16]} />
          <meshStandardMaterial color="#1a202c" metalness={0.95} roughness={0.1} />
        </mesh>
        
        {/* Crank throws (4 throws for boxer configuration) */}
        {[0, 1, 2, 3].map((i) => {
          const zPos = (i - 1.5) * ENGINE.cylinderSpacing;
          const angle = i < 2 ? 0 : Math.PI; // Opposite banks
          return (
            <group key={`throw-${i}`} position={[0, 0, zPos]}>
              {/* Crank throw */}
              <mesh 
                position={[Math.cos(angle) * ENGINE.crankRadius / 2, Math.sin(angle) * ENGINE.crankRadius / 2, 0]}
                rotation={[0, 0, angle]}
              >
                <boxGeometry args={[ENGINE.crankRadius, 0.15, 0.15]} />
                <meshStandardMaterial color="#2d3748" metalness={0.9} roughness={0.2} />
              </mesh>
              {/* Crank pin */}
              <mesh position={[Math.cos(angle) * ENGINE.crankRadius, Math.sin(angle) * ENGINE.crankRadius, 0]}>
                <cylinderGeometry args={[0.08, 0.08, 0.3, 12]} />
                <meshStandardMaterial color="#1a202c" metalness={0.95} roughness={0.1} />
              </mesh>
            </group>
          );
        })}
      </group>
      
      {/* ─── Cylinders and Pistons (Bank A - Left) ─── */}
      {[0, 2].map((i) => {
        const zPos = (i - 1.5) * ENGINE.cylinderSpacing;
        const xOffset = getExplodedOffset('cylinderLeft')[0];
        
        return (
          <group key={`bank-a-${i}`} position={[xOffset, 0, zPos]}>
            {/* Cylinder barrel */}
            <mesh rotation={[0, 0, Math.PI / 2]} position={[ENGINE.crankcaseRadius + ENGINE.cylinderLength / 2, 0, 0]}>
              <cylinderGeometry args={[ENGINE.cylinderRadius, ENGINE.cylinderRadius, ENGINE.cylinderLength, 24]} />
              <meshStandardMaterial 
                color="#718096" 
                metalness={0.7} 
                roughness={0.4}
                transparent
                opacity={0.8}
              />
            </mesh>
            
            {/* Cylinder head with CHT shader */}
            <mesh 
              ref={(el) => { if (el) cylinderHeadsRef.current[i] = el; }}
              position={[ENGINE.crankcaseRadius + ENGINE.cylinderLength + 0.1, 0, 0]}
              rotation={[0, 0, Math.PI / 2]}
            >
              <cylinderGeometry args={[ENGINE.cylinderRadius * 1.1, ENGINE.cylinderRadius * 1.1, 0.2, 24]} />
              <primitive object={createCHTShaderMaterial()} attach="material" />
            </mesh>
            
            {/* Piston */}
            <group ref={(el) => { if (el) pistonsRef.current[i] = el; }}>
              <mesh position={[ENGINE.crankcaseRadius * 0.5, 0, 0]}>
                <cylinderGeometry args={[ENGINE.pistonRadius, ENGINE.pistonRadius, ENGINE.pistonHeight, 16]} />
                <meshStandardMaterial color="#a0aec0" metalness={0.85} roughness={0.2} />
              </mesh>
              {/* Connecting rod */}
              <mesh position={[ENGINE.crankcaseRadius * 0.3, -ENGINE.rodLength / 2, 0]}>
                <boxGeometry args={[0.08, ENGINE.rodLength, 0.06]} />
                <meshStandardMaterial color="#4a5568" metalness={0.8} roughness={0.3} />
              </mesh>
            </group>
          </group>
        );
      })}
      
      {/* ─── Cylinders and Pistons (Bank B - Right) ─── */}
      {[1, 3].map((i) => {
        const zPos = (i - 1.5) * ENGINE.cylinderSpacing;
        const xOffset = getExplodedOffset('cylinderRight')[0];
        
        return (
          <group key={`bank-b-${i}`} position={[xOffset, 0, zPos]}>
            {/* Cylinder barrel */}
            <mesh rotation={[0, 0, -Math.PI / 2]} position={[-ENGINE.crankcaseRadius - ENGINE.cylinderLength / 2, 0, 0]}>
              <cylinderGeometry args={[ENGINE.cylinderRadius, ENGINE.cylinderRadius, ENGINE.cylinderLength, 24]} />
              <meshStandardMaterial 
                color="#718096" 
                metalness={0.7} 
                roughness={0.4}
                transparent
                opacity={0.8}
              />
            </mesh>
            
            {/* Cylinder head with CHT shader */}
            <mesh 
              ref={(el) => { if (el) cylinderHeadsRef.current[i] = el; }}
              position={[-ENGINE.crankcaseRadius - ENGINE.cylinderLength - 0.1, 0, 0]}
              rotation={[0, 0, -Math.PI / 2]}
            >
              <cylinderGeometry args={[ENGINE.cylinderRadius * 1.1, ENGINE.cylinderRadius * 1.1, 0.2, 24]} />
              <primitive object={createCHTShaderMaterial()} attach="material" />
            </mesh>
            
            {/* Piston */}
            <group ref={(el) => { if (el) pistonsRef.current[i] = el; }}>
              <mesh position={[-ENGINE.crankcaseRadius * 0.5, 0, 0]}>
                <cylinderGeometry args={[ENGINE.pistonRadius, ENGINE.pistonRadius, ENGINE.pistonHeight, 16]} />
                <meshStandardMaterial color="#a0aec0" metalness={0.85} roughness={0.2} />
              </mesh>
              {/* Connecting rod */}
              <mesh position={[-ENGINE.crankcaseRadius * 0.3, -ENGINE.rodLength / 2, 0]}>
                <boxGeometry args={[0.08, ENGINE.rodLength, 0.06]} />
                <meshStandardMaterial color="#4a5568" metalness={0.8} roughness={0.3} />
              </mesh>
            </group>
          </group>
        );
      })}
      
      {/* ─── Exhaust Manifolds ─── */}
      <group position={getExplodedOffset('exhaustLeft')}>
        {/* Left bank exhaust */}
        <mesh position={[ENGINE.crankcaseRadius + ENGINE.cylinderLength + 0.3, -0.3, 0]}>
          <cylinderGeometry args={[0.08, 0.1, 0.6, 12]} />
          <meshStandardMaterial color="#742a2a" metalness={0.6} roughness={0.5} />
        </mesh>
        {[0, 2].map((i) => (
          <mesh 
            key={`exhaust-left-${i}`}
            position={[
              ENGINE.crankcaseRadius + ENGINE.cylinderLength + 0.3, 
              -0.1, 
              (i - 1.5) * ENGINE.cylinderSpacing
            ]}
          >
            <cylinderGeometry args={[0.05, 0.05, 0.4, 8]} />
            <meshStandardMaterial color="#9b2c2c" metalness={0.7} roughness={0.4} />
          </mesh>
        ))}
      </group>
      
      <group position={getExplodedOffset('exhaustRight')}>
        {/* Right bank exhaust */}
        <mesh position={[-ENGINE.crankcaseRadius - ENGINE.cylinderLength - 0.3, -0.3, 0]}>
          <cylinderGeometry args={[0.08, 0.1, 0.6, 12]} />
          <meshStandardMaterial color="#742a2a" metalness={0.6} roughness={0.5} />
        </mesh>
        {[1, 3].map((i) => (
          <mesh 
            key={`exhaust-right-${i}`}
            position={[
              -ENGINE.crankcaseRadius - ENGINE.cylinderLength - 0.3, 
              -0.1, 
              (i - 1.5) * ENGINE.cylinderSpacing
            ]}
          >
            <cylinderGeometry args={[0.05, 0.05, 0.4, 8]} />
            <meshStandardMaterial color="#9b2c2c" metalness={0.7} roughness={0.4} />
          </mesh>
        ))}
      </group>
    </group>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Camera Controller Component
// ══════════════════════════════════════════════════════════════════════════════

interface CameraControllerProps {
  preset: CameraPreset;
  autoRotate: boolean;
}

function CameraController({ preset, autoRotate }: CameraControllerProps) {
  const { camera } = useThree();
  const controlsRef = useRef<any>(null);
  
  useEffect(() => {
    // Animate camera to preset position
    const startPos = new THREE.Vector3().copy(camera.position);
    const endPos = new THREE.Vector3(...preset.position);
    const startTarget = controlsRef.current?.target ?? new THREE.Vector3();
    const endTarget = new THREE.Vector3(...preset.target);
    
    let progress = 0;
    const duration = 1000; // ms
    const startTime = Date.now();
    
    const animate = () => {
      progress = Math.min((Date.now() - startTime) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3); // Ease out cubic
      
      camera.position.lerpVectors(startPos, endPos, eased);
      
      if (controlsRef.current) {
        controlsRef.current.target.lerpVectors(startTarget, endTarget, eased);
        controlsRef.current.update();
      }
      
      if (progress < 1) {
        requestAnimationFrame(animate);
      }
    };
    
    animate();
  }, [preset, camera]);
  
  return (
    <OrbitControls
      ref={controlsRef}
      autoRotate={autoRotate}
      autoRotateSpeed={0.5}
      enableDamping
      dampingFactor={0.05}
      minDistance={3}
      maxDistance={20}
      maxPolarAngle={Math.PI * 0.85}
    />
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Main Engine3DView Component
// ══════════════════════════════════════════════════════════════════════════════

export default function Engine3DView({ 
  className,
  showControls = true,
}: Engine3DViewProps) {
  const { currentFrame } = useTelemetry();
  
  // State
  const [cameraPreset, setCameraPreset] = useState<CameraPreset>(CAMERA_PRESETS[0]);
  const [autoRotate, setAutoRotate] = useState(true);
  const [explodedView, setExplodedView] = useState(0);
  
  // RPM for status display
  const rpm = currentFrame?.rpm ?? 0;
  const cht = currentFrame?.cht ?? [0, 0, 0, 0];
  
  return (
    <div className={clsx('relative w-full h-full', className)}>
      {/* 3D Canvas */}
      <Canvas
        shadows
        dpr={[1, 2]}
        gl={{ 
          antialias: true,
          alpha: false,
          powerPreference: 'high-performance',
        }}
        style={{ background: '#0b0f19' }}
      >
        {/* Camera */}
        <PerspectiveCamera
          makeDefault
          position={cameraPreset.position}
          fov={50}
          near={0.1}
          far={100}
        />
        
        {/* Lighting */}
        <ambientLight intensity={0.4} />
        <directionalLight
          position={[10, 10, 5]}
          intensity={1}
          castShadow
          shadow-mapSize={[2048, 2048]}
        />
        <pointLight position={[-5, 5, -5]} intensity={0.5} color="#06b6d4" />
        <pointLight position={[5, -5, 5]} intensity={0.3} color="#f59e0b" />
        
        {/* Environment for reflections */}
        <Environment preset="studio" />
        
        {/* Controls */}
        <CameraController preset={cameraPreset} autoRotate={autoRotate} />
        
        {/* Engine */}
        <EngineScene explodedView={explodedView} />
        
        {/* Grid helper */}
        <gridHelper args={[20, 20, '#1f2937', '#111827']} position={[0, -3, 0]} />
      </Canvas>
      
      {/* ─── Overlay Controls ─── */}
      {showControls && (
        <div className="absolute bottom-4 left-4 right-4 flex flex-wrap gap-2">
          {/* Camera Presets */}
          <div className="glass-card p-2 flex gap-2">
            <Camera className="w-4 h-4 text-cockpit-muted mt-1" />
            {CAMERA_PRESETS.map((preset) => (
              <button
                key={preset.name}
                onClick={() => setCameraPreset(preset)}
                className={clsx(
                  'px-3 py-1.5 rounded text-xs font-medium transition-colors',
                  cameraPreset.name === preset.name
                    ? 'bg-cyber-cyan text-cockpit-bg'
                    : 'bg-cockpit-surface hover:bg-cockpit-border text-white'
                )}
              >
                {preset.name}
              </button>
            ))}
          </div>
          
          {/* View Controls */}
          <div className="glass-card p-2 flex items-center gap-3">
            {/* Auto-rotate toggle */}
            <button
              onClick={() => setAutoRotate(!autoRotate)}
              className={clsx(
                'p-2 rounded transition-colors',
                autoRotate ? 'bg-cyber-cyan/20 text-cyber-cyan' : 'bg-cockpit-surface text-cockpit-muted'
              )}
              title="Toggle auto-rotation"
            >
              <RotateCcw className="w-4 h-4" />
            </button>
            
            {/* Exploded view slider */}
            <div className="flex items-center gap-2">
              <Layers className="w-4 h-4 text-cockpit-muted" />
              <span className="text-xs text-cockpit-muted">Explode</span>
              <input
                type="range"
                min="0"
                max="100"
                value={explodedView * 100}
                onChange={(e) => setExplodedView(Number(e.target.value) / 100)}
                className="w-24 h-1 bg-cockpit-border rounded-full appearance-none cursor-pointer
                  [&::-webkit-slider-thumb]:appearance-none
                  [&::-webkit-slider-thumb]:w-3
                  [&::-webkit-slider-thumb]:h-3
                  [&::-webkit-slider-thumb]:rounded-full
                  [&::-webkit-slider-thumb]:bg-cyber-cyan
                  [&::-webkit-slider-thumb]:cursor-pointer"
              />
            </div>
          </div>
          
          {/* Status Display */}
          <div className="glass-card px-3 py-2 flex items-center gap-4">
            <div className="text-center">
              <p className="text-xs text-cockpit-muted">RPM</p>
              <p className="data-display text-hud-amber">{rpm.toFixed(0)}</p>
            </div>
            <div className="text-center">
              <p className="text-xs text-cockpit-muted">CHT</p>
              <p className="data-display text-white">
                {cht[0]?.toFixed(0) ?? '---'}°C
              </p>
            </div>
          </div>
        </div>
      )}
      
      {/* ─── CHT Legend ─── */}
      {showControls && (
        <div className="absolute top-4 right-4 glass-card p-3">
          <p className="text-xs text-cockpit-muted mb-2">CHT Heatmap</p>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded bg-nominal-green" />
            <span className="text-xs">&lt;140°C</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded bg-hud-amber" />
            <span className="text-xs">140-190°C</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded bg-alert-red animate-pulse" />
            <span className="text-xs">&gt;210°C</span>
          </div>
        </div>
      )}
    </div>
  );
}
