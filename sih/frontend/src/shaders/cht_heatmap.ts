// ══════════════════════════════════════════════════════════════════════════════
// Cylinder Head Temperature (CHT) Heatmap Shader
// ══════════════════════════════════════════════════════════════════════════════
//
// Dynamic thermal visualization for 4-cylinder aero engine:
// - Green (< 140°C): Nominal operating temperature
// - Yellow/Amber (140°C - 190°C): Elevated temperature warning
// - Glowing Red (> 210°C): Critical overheat with pulsing emissive
//
// ══════════════════════════════════════════════════════════════════════════════

export const chtVertexShader = `
  // Uniforms
  uniform float u_cht;           // Current cylinder temperature (°C)
  uniform float u_time;          // Animation time
  uniform float u_pulseSpeed;    // Pulse speed for critical warning
  uniform float u_pulseIntensity; // Pulse intensity
  
  // Varyings
  varying float v_temperature;
  varying float v_normalizedTemp;
  varying vec3 v_normal;
  varying vec3 v_position;
  varying float v_pulse;
  
  // Temperature thresholds
  const float TEMP_NOMINAL_MAX = 140.0;
  const float TEMP_WARNING_MAX = 190.0;
  const float TEMP_CRITICAL_MIN = 210.0;
  const float TEMP_MAX = 300.0;
  
  void main() {
    v_temperature = u_cht;
    v_normal = normalize(normalMatrix * normal);
    v_position = (modelViewMatrix * vec4(position, 1.0)).xyz;
    
    // Normalize temperature to 0-1 range
    v_normalizedTemp = clamp(u_cht / TEMP_MAX, 0.0, 1.0);
    
    // Calculate pulse for critical temperatures
    float isCritical = step(TEMP_CRITICAL_MIN, u_cht);
    v_pulse = isCritical * (0.5 + 0.5 * sin(u_time * u_pulseSpeed)) * u_pulseIntensity;
    
    // Subtle vertex displacement for heat shimmer effect
    float heatDisplacement = v_normalizedTemp * 0.02 * sin(position.y * 10.0 + u_time * 2.0);
    vec3 displacedPosition = position + normal * heatDisplacement;
    
    gl_Position = projectionMatrix * modelViewMatrix * vec4(displacedPosition, 1.0);
  }
`;

export const chtFragmentShader = `
  // Uniforms
  uniform float u_cht;
  uniform float u_time;
  uniform float u_emissiveStrength;
  
  // Varyings from vertex shader
  varying float v_temperature;
  varying float v_normalizedTemp;
  varying vec3 v_normal;
  varying vec3 v_position;
  varying float v_pulse;
  
  // Temperature thresholds
  const float TEMP_NOMINAL_MAX = 140.0;
  const float TEMP_WARNING_MAX = 190.0;
  const float TEMP_CRITICAL_MIN = 210.0;
  
  // Color palette
  const vec3 COLOR_NOMINAL = vec3(0.063, 0.725, 0.506);      // #10b981 (Green)
  const vec3 COLOR_WARNING = vec3(0.961, 0.620, 0.043);      // #f59e0b (Amber)
  const vec3 COLOR_CRITICAL = vec3(0.937, 0.267, 0.267);     // #ef4444 (Red)
  const vec3 COLOR_HOT = vec3(1.0, 0.2, 0.1);                // Bright red for extreme
  
  // Simple noise function for heat shimmer
  float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
  }
  
  void main() {
    // Base color based on temperature
    vec3 baseColor;
    float emissive = 0.0;
    
    if (v_temperature < TEMP_NOMINAL_MAX) {
      // Nominal: Green
      float t = v_temperature / TEMP_NOMINAL_MAX;
      baseColor = mix(vec3(0.04, 0.5, 0.3), COLOR_NOMINAL, t);
      emissive = 0.1;
    } else if (v_temperature < TEMP_WARNING_MAX) {
      // Warning: Green -> Amber transition
      float t = (v_temperature - TEMP_NOMINAL_MAX) / (TEMP_WARNING_MAX - TEMP_NOMINAL_MAX);
      baseColor = mix(COLOR_NOMINAL, COLOR_WARNING, t);
      emissive = 0.2 + t * 0.3;
    } else if (v_temperature < TEMP_CRITICAL_MIN) {
      // Transition: Amber -> Red
      float t = (v_temperature - TEMP_WARNING_MAX) / (TEMP_CRITICAL_MIN - TEMP_WARNING_MAX);
      baseColor = mix(COLOR_WARNING, COLOR_CRITICAL, t);
      emissive = 0.5 + t * 0.3;
    } else {
      // Critical: Red with pulsing glow
      float t = min((v_temperature - TEMP_CRITICAL_MIN) / 90.0, 1.0);
      baseColor = mix(COLOR_CRITICAL, COLOR_HOT, t);
      emissive = 0.8 + v_pulse;
      
      // Add heat shimmer noise
      float noise = hash(v_position.xy * 5.0 + u_time) * 0.1;
      baseColor += noise;
    }
    
    // Simple lighting
    vec3 lightDir = normalize(vec3(1.0, 1.0, 1.0));
    float diff = max(dot(v_normal, lightDir), 0.0);
    float ambient = 0.3;
    
    vec3 finalColor = baseColor * (ambient + diff * 0.7);
    
    // Add emissive glow
    finalColor += baseColor * emissive * u_emissiveStrength;
    
    // Fresnel rim lighting for metallic effect
    vec3 viewDir = normalize(-v_position);
    float fresnel = pow(1.0 - max(dot(viewDir, v_normal), 0.0), 3.0);
    finalColor += vec3(0.3, 0.4, 0.5) * fresnel * 0.3;
    
    gl_FragColor = vec4(finalColor, 1.0);
  }
`;

// ══════════════════════════════════════════════════════════════════════════════
// Shader Material Factory
// ══════════════════════════════════════════════════════════════════════════════

import * as THREE from 'three';

export interface CHTShaderUniforms {
  u_cht: { value: number };
  u_time: { value: number };
  u_pulseSpeed: { value: number };
  u_pulseIntensity: { value: number };
  u_emissiveStrength: { value: number };
}

export function createCHTShaderMaterial(): THREE.ShaderMaterial {
  const uniforms: CHTShaderUniforms = {
    u_cht: { value: 180.0 },
    u_time: { value: 0.0 },
    u_pulseSpeed: { value: 4.0 },
    u_pulseIntensity: { value: 0.5 },
    u_emissiveStrength: { value: 1.5 },
  };

  return new THREE.ShaderMaterial({
    vertexShader: chtVertexShader,
    fragmentShader: chtFragmentShader,
    uniforms: uniforms as unknown as Record<string, THREE.IUniform>,
    side: THREE.DoubleSide,
  });
}
