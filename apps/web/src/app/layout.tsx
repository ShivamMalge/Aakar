import type { ReactNode } from "react";

export const metadata = {
  title: "Aakar",
  description: "Syllabus-grounded interactive 3D learning components",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
