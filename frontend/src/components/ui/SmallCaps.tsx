import type { CSSProperties, ReactNode } from "react";

interface Props {
  children: ReactNode;
  color?: string;
  size?: number;
  style?: CSSProperties;
}

export default function SmallCaps({
  children,
  color = "#9b9c99",
  size = 11,
  style,
}: Props) {
  return (
    <span
      style={{
        fontSize: size,
        fontWeight: 600,
        color,
        textTransform: "uppercase",
        letterSpacing: "0.12em",
        ...style,
      }}
    >
      {children}
    </span>
  );
}
