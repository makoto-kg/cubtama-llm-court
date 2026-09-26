"use client";

import { useConfig } from "@/hooks/useApi";
import { ROLE_LABELS } from "@/lib/labels";

export function SettingsView() {
  const { data: config, error } = useConfig();

  if (error) return <p className="text-red-300">API に接続できません: {error}</p>;
  if (!config) return <p>読み込み中…</p>;
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-white/20 text-left">
          <th className="p-1">役割</th>
          <th className="p-1">モデル</th>
          <th className="p-1">推論</th>
          <th className="p-1">プロバイダ</th>
          <th className="p-1">構造化出力</th>
          <th className="p-1">並列</th>
        </tr>
      </thead>
      <tbody>
        {config.roles.map((r) => (
          <tr key={r.role} className="border-b border-white/10">
            <td className="p-1">
              {ROLE_LABELS[r.role] ?? r.role} <span className="opacity-60">({r.role})</span>
            </td>
            <td className="p-1">
              {r.model} <span className="opacity-60">({r.model_key})</span>
            </td>
            <td className="p-1">{r.reasoning ?? "-"}</td>
            <td className="p-1">
              {r.provider} <span className="opacity-60">{r.base_url}</span>
            </td>
            <td className="p-1">
              {[r.json_schema && "json_schema", r.json_mode && "json_object", "prompt"]
                .filter(Boolean)
                .join(" → ")}
            </td>
            <td className="p-1">{r.max_concurrency}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
