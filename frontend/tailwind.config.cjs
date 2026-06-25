/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        graphite: {
          950: "#08090b",
          925: "#0d0f12",
          900: "#12151a",
          850: "#171b21",
          800: "#1f242c",
          700: "#2d3440"
        },
        accent: {
          500: "#3b82f6",
          400: "#60a5fa"
        }
      },
      boxShadow: {
        composer: "0 -18px 50px rgba(8, 9, 11, 0.48)"
      }
    }
  },
  plugins: []
};
