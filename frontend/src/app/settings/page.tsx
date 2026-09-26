import { SettingsView } from "@/components/SettingsView";

export default function SettingsPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">設定</h1>
      <p className="text-sm opacity-80">
        役割ごとのモデル割り当て(backend の models.yaml)。編集は backend の設定ファイルで行います。
      </p>
      <SettingsView />
    </div>
  );
}
