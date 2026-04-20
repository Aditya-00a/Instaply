"use client";

import { useRef, useMemo } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Float, MeshDistortMaterial, Environment } from "@react-three/drei";
import type { Mesh } from "three";

/**
 * The hero 3D scene.
 *
 * Three soft, glassy shapes orbit slowly behind the headline. Tasteful, not
 * gamer. Uses Drei's Float helper for organic motion + MeshDistortMaterial
 * for that subtle morphing surface.
 */
function FloatingShape({
  position,
  color,
  scale = 1,
  geometry = "icosa",
  speed = 1,
}: {
  position: [number, number, number];
  color: string;
  scale?: number;
  geometry?: "icosa" | "torus" | "octa";
  speed?: number;
}) {
  const ref = useRef<Mesh>(null);

  useFrame((_, delta) => {
    if (!ref.current) return;
    ref.current.rotation.x += delta * 0.15 * speed;
    ref.current.rotation.y += delta * 0.18 * speed;
  });

  const geo = useMemo(() => {
    switch (geometry) {
      case "torus":
        return <torusKnotGeometry args={[0.7, 0.22, 128, 32]} />;
      case "octa":
        return <octahedronGeometry args={[1, 2]} />;
      default:
        return <icosahedronGeometry args={[1, 4]} />;
    }
  }, [geometry]);

  return (
    <Float speed={1.6 * speed} rotationIntensity={0.6} floatIntensity={1.2}>
      <mesh ref={ref} position={position} scale={scale} castShadow>
        {geo}
        <MeshDistortMaterial
          color={color}
          distort={0.32}
          speed={1.4}
          roughness={0.18}
          metalness={0.45}
          transparent
          opacity={0.92}
        />
      </mesh>
    </Float>
  );
}

export function HeroScene() {
  return (
    <Canvas
      shadows
      dpr={[1, 2]}
      camera={{ position: [0, 0, 6], fov: 45 }}
      gl={{ antialias: true, alpha: true }}
    >
      <ambientLight intensity={0.55} />
      <directionalLight
        position={[4, 6, 5]}
        intensity={1.4}
        castShadow
        shadow-mapSize={[1024, 1024]}
      />
      <pointLight position={[-4, -2, -2]} intensity={0.6} color="#5f8cff" />
      <pointLight position={[3, -3, 2]} intensity={0.4} color="#a78bfa" />

      <FloatingShape
        position={[-2.2, 1.0, 0]}
        color="#5f8cff"
        scale={0.85}
        geometry="icosa"
      />
      <FloatingShape
        position={[2.4, 0.4, -0.5]}
        color="#a78bfa"
        scale={0.65}
        geometry="torus"
        speed={0.85}
      />
      <FloatingShape
        position={[0.2, -1.4, 0.5]}
        color="#60a5fa"
        scale={0.55}
        geometry="octa"
        speed={1.15}
      />

      <Environment preset="city" />
    </Canvas>
  );
}
