import { useEffect, useRef } from "react";

const VERTEX_SHADER = `
  attribute vec2 aPosition;
  varying vec2 vUv;

  void main() {
    vUv = aPosition * 0.5 + 0.5;
    gl_Position = vec4(aPosition, 0.0, 1.0);
  }
`;

const FRAGMENT_SHADER = `
  precision mediump float;
  uniform float uTime;
  uniform vec3 uColor;
  uniform vec3 uDarkColor;
  varying vec2 vUv;

  mat2 rotate2d(float angle) {
    float sine = sin(angle);
    float cosine = cos(angle);
    return mat2(cosine, -sine, sine, cosine);
  }

  void main() {
    vec2 point = (vUv * 2.0 - 1.0) * 1.12;
    float angle = atan(point.y, point.x);
    float edgeWarp =
      sin(angle * 5.0 + uTime * 0.92) * 0.014 +
      sin(angle * 9.0 - uTime * 0.57) * 0.007 +
      sin(angle * 3.0 + uTime * 0.31) * 0.011;
    float radius = 0.88 + edgeWarp;
    float radialDistance = length(point);

    vec2 spherePoint = point / radius;
    float sphereZ = sqrt(max(0.0, 1.0 - dot(spherePoint, spherePoint)));
    vec3 normal = normalize(vec3(spherePoint, sphereZ));

    normal.xz = rotate2d(uTime * 0.19 + sin(uTime * 0.31) * 0.16) * normal.xz;
    normal.yz = rotate2d(sin(uTime * 0.27) * 0.22) * normal.yz;

    float longitude = atan(normal.z, normal.x);
    float latitude = asin(clamp(normal.y, -1.0, 1.0));
    float longitudeWarp = longitude + sin(latitude * 5.0 + uTime * 0.72) * 0.15;
    float latitudeWarp = latitude + sin(longitude * 4.0 - uTime * 0.48) * 0.1;
    float longitudeGrid = 1.0 - smoothstep(0.0, 0.105, abs(sin(longitudeWarp * 7.0)));
    float latitudeGrid = 1.0 - smoothstep(0.0, 0.105, abs(sin(latitudeWarp * 9.0)));
    float grid = max(longitudeGrid, latitudeGrid);

    vec3 lightDirection = normalize(vec3(-0.45, 0.62, 0.8));
    float diffuse = max(0.0, dot(normal, lightDirection));
    float rim = pow(1.0 - max(0.0, normal.z), 2.3);
    float movingGlow = 0.5 + 0.5 * sin(normal.x * 5.2 + normal.y * 3.7 + uTime * 0.8);
    vec3 darkColor = mix(uDarkColor * 0.34, uColor * 0.09, diffuse);
    vec3 surfaceColor =
      darkColor +
      uColor * diffuse * 0.2 +
      uColor * grid * (0.2 + movingGlow * 0.18) +
      uColor * rim * 0.28;

    float alphaEdge = 1.0 - smoothstep(radius - 0.045, radius + 0.012, radialDistance);
    float translucency = 0.6 + diffuse * 0.16 + rim * 0.12;
    gl_FragColor = vec4(surfaceColor, alphaEdge * translucency);
  }
`;

function compileShader(
  gl: WebGLRenderingContext,
  type: number,
  source: string,
): WebGLShader {
  const shader = gl.createShader(type);
  if (!shader) throw new Error("Unable to create sphere shader");
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const message = gl.getShaderInfoLog(shader) ?? "Unknown sphere shader error";
    gl.deleteShader(shader);
    throw new Error(message);
  }
  return shader;
}

export function WarpedSphereSurface({
  color,
  colorVariable,
  phase = 0,
}: {
  color: readonly [number, number, number];
  colorVariable?: string;
  phase?: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (typeof navigator !== "undefined" && /jsdom/i.test(navigator.userAgent)) return undefined;
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const gl = canvas.getContext("webgl", {
      alpha: true,
      antialias: true,
      premultipliedAlpha: false,
      powerPreference: "low-power",
    });
    if (!gl) return undefined;

    let vertexShader: WebGLShader;
    let fragmentShader: WebGLShader;
    const program = gl.createProgram();
    if (!program) return undefined;
    try {
      vertexShader = compileShader(gl, gl.VERTEX_SHADER, VERTEX_SHADER);
      fragmentShader = compileShader(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
    } catch (error) {
      console.warn("Warped sphere renderer could not start.", error);
      gl.deleteProgram(program);
      return undefined;
    }
    gl.attachShader(program, vertexShader);
    gl.attachShader(program, fragmentShader);
    gl.linkProgram(program);
    gl.deleteShader(vertexShader);
    gl.deleteShader(fragmentShader);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      gl.deleteProgram(program);
      return undefined;
    }

    const buffer = gl.createBuffer();
    if (!buffer) {
      gl.deleteProgram(program);
      return undefined;
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
      gl.STATIC_DRAW,
    );
    gl.useProgram(program);
    const position = gl.getAttribLocation(program, "aPosition");
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
    const colorLocation = gl.getUniformLocation(program, "uColor");
    const darkColorLocation = gl.getUniformLocation(program, "uDarkColor");
    const applyThemeColor = () => {
      const rootStyles = window.getComputedStyle(document.documentElement);
      const rawValue = colorVariable
        ? rootStyles.getPropertyValue(colorVariable).trim()
        : "";
      const components = rawValue.split(/[\s,]+/).map(Number);
      const themedColor = components.length >= 3 && components.slice(0, 3).every(Number.isFinite)
        ? components
        : color;
      const rawDarkColor = rootStyles.getPropertyValue("--guided-bg-rgb").trim();
      const darkComponents = rawDarkColor.split(/[\s,]+/).map(Number);
      const themedDarkColor = darkComponents.length >= 3 && darkComponents.slice(0, 3).every(Number.isFinite)
        ? darkComponents
        : [4, 14, 18];
      gl.uniform3f(
        colorLocation,
        themedColor[0] / 255,
        themedColor[1] / 255,
        themedColor[2] / 255,
      );
      gl.uniform3f(
        darkColorLocation,
        themedDarkColor[0] / 255,
        themedDarkColor[1] / 255,
        themedDarkColor[2] / 255,
      );
    };
    applyThemeColor();
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let animationFrame = 0;

    const resize = () => {
      const bounds = canvas.getBoundingClientRect();
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5);
      const width = Math.max(1, Math.round(bounds.width * pixelRatio));
      const height = Math.max(1, Math.round(bounds.height * pixelRatio));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      gl.viewport(0, 0, width, height);
    };

    const render = (now: number) => {
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      const time = reducedMotion.matches ? phase : now / 1000 + phase;
      gl.uniform1f(gl.getUniformLocation(program, "uTime"), time);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
      if (!reducedMotion.matches) animationFrame = window.requestAnimationFrame(render);
    };
    const handleMotionPreference = () => {
      window.cancelAnimationFrame(animationFrame);
      animationFrame = window.requestAnimationFrame(render);
    };
    const observer = new ResizeObserver(() => {
      resize();
      if (reducedMotion.matches) render(0);
    });
    const themeObserver = new MutationObserver(() => {
      applyThemeColor();
      if (reducedMotion.matches) render(0);
    });
    observer.observe(canvas);
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    resize();
    reducedMotion.addEventListener("change", handleMotionPreference);
    animationFrame = window.requestAnimationFrame(render);

    return () => {
      window.cancelAnimationFrame(animationFrame);
      observer.disconnect();
      themeObserver.disconnect();
      reducedMotion.removeEventListener("change", handleMotionPreference);
      gl.deleteBuffer(buffer);
      gl.deleteProgram(program);
    };
  }, [color, colorVariable, phase]);

  return <canvas ref={canvasRef} className="warped-sphere-canvas" aria-hidden="true" />;
}
