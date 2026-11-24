import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        slate: {
          50: "#fbfaf7",
          100: "#f3f0e9",
          200: "#e6e0d5",
          300: "#d2c8b8",
          400: "#a69b8a",
          500: "#776f62",
          600: "#5f584d",
          700: "#484239",
          800: "#332f29",
          900: "#24211d",
          950: "#161411",
        },
        indigo: {
          50: "#eef5fb",
          100: "#dbeaf6",
          200: "#c2dced",
          300: "#98c2dc",
          400: "#6ca0c3",
          500: "#3d7fa9",
          600: "#285f89",
          700: "#1f4b70",
          800: "#1a3e5e",
          900: "#142f49",
          950: "#0c1d2e",
        },
      },
      fontFamily: {
        display: ["Georgia", "Times New Roman", "serif"],
      },
    },
  },
  plugins: [],
};
export default config;
