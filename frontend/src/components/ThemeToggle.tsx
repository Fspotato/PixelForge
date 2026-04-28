import { useTheme } from "../hooks/useTheme"

export function ThemeToggle() {
  const { dark, toggle } = useTheme()

  return (
    <button
      onClick={toggle}
      className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors text-lg"
      title={dark ? "切換為淺色模式" : "切換為深色模式"}
    >
      {dark ? "☀️" : "🌙"}
    </button>
  )
}
