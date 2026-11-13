import { useEffect, useRef } from "react";
import type { CoreState } from "../types";

const COLOR: Record<CoreState, string> = {
  idle: "#5de4ff",
  listening: "#8ff6ff",
  thinking: "#f0d78c",
  speaking: "#9eb6ff",
  approval: "#ff6b81",
};

export function Reactor({ state, level }: { state: CoreState; level: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef(state);
  const levelRef = useRef(level);
  stateRef.current = state;
  levelRef.current = level;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let frame = 0;
    let raf = 0;

    const draw = () => {
      const rect = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      const width = Math.max(1, Math.floor(rect.width * ratio));
      const height = Math.max(1, Math.floor(rect.height * ratio));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      const ctx = context;
      ctx.clearRect(0, 0, width, height);
      const cx = width / 2;
      const cy = height / 2;
      const radius = Math.min(width, height) * 0.36;
      const color = COLOR[stateRef.current];
      const pulse = reduced ? 0 : frame / 60;
      const audio = levelRef.current;
      ctx.save();
      ctx.translate(cx, cy);
      ctx.strokeStyle = "rgba(94, 190, 230, 0.25)";
      ctx.lineWidth = 1.2 * ratio;
      for (let ring = 0; ring < 3; ring += 1) {
        ctx.beginPath();
        ctx.arc(0, 0, radius * (1.15 + ring * 0.16), 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.strokeStyle = color;
      ctx.globalAlpha = 0.85;
      ctx.lineWidth = 3 * ratio;
      ctx.beginPath();
      const sweep = pulse * (stateRef.current === "thinking" ? 2.4 : 0.7);
      ctx.arc(0, 0, radius * (1.02 + audio * 0.08), sweep, sweep + Math.PI * 1.35);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(0, 0, radius * 0.78, -sweep * 1.3, -sweep * 1.3 + Math.PI);
      ctx.stroke();
      ctx.globalAlpha = 1;
      const glow = ctx.createRadialGradient(0, 0, radius * 0.1, 0, 0, radius * (0.62 + audio * 0.2));
      glow.addColorStop(0, color);
      glow.addColorStop(0.45, hexAlpha(color, 0.35));
      glow.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(0, 0, radius * (0.7 + audio * 0.12), 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#f7fbff";
      ctx.beginPath();
      ctx.arc(0, 0, radius * (0.12 + audio * 0.05), 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "rgba(180, 230, 255, 0.45)";
      ctx.lineWidth = 1 * ratio;
      for (let tick = 0; tick < 24; tick += 1) {
        const angle = (tick / 24) * Math.PI * 2 + (reduced ? 0 : pulse * 0.2);
        const inner = radius * 1.28;
        const outer = inner + (tick % 6 === 0 ? 12 : 6) * ratio;
        ctx.beginPath();
        ctx.moveTo(Math.cos(angle) * inner, Math.sin(angle) * inner);
        ctx.lineTo(Math.cos(angle) * outer, Math.sin(angle) * outer);
        ctx.stroke();
      }
      ctx.restore();
      frame += 1;
      if (!reduced) raf = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <div className={`reactor reactor-${state}`}>
      <canvas ref={canvasRef} />
      <div className="reactor-readout">
        <span>{state}</span>
        <strong>{Math.round(level * 100).toString().padStart(2, "0")}</strong>
      </div>
    </div>
  );
}

function hexAlpha(hex: string, alpha: number): string {
  const value = hex.replace("#", "");
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
