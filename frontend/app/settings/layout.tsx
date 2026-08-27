import type { Metadata } from "next";

export const metadata: Metadata = { title: "الإعدادات" };

export default function SettingsLayout({ children }: LayoutProps<"/settings">) {
  return children;
}
