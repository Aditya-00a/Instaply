import type { Config } from "tailwindcss";
import typography from "@tailwindcss/typography";

export default {
  content: ["./app/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0b0d10",
        accent: "#5f8cff",
      },
    },
  },
  plugins: [typography],
} satisfies Config;
