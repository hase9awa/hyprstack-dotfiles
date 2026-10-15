return {
  "Wansmer/langmapper.nvim",
  lazy = false,
  priority = 1,
  opts = {
    hack_keymap = true,
  },
  config = function(_, opts)
    require("langmapper").setup(opts)
    require("langmapper").automapping({
      global = true,
      buffer = true,
    })
  end,
}
