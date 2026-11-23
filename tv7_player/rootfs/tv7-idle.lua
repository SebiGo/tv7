-- Idle screen: while mpv plays nothing (start, stop, end of stream, idle stop), the TV7 logo is shown in the middle of a black
-- screen. The logo is an OSD overlay (raw premultiplied BGRA prepared by control.py), scaled to a share of the screen width.
-- Options (--script-opts): tv7idle-file, tv7idle-w, tv7idle-h (size of the raw image), tv7idle-width (share of the screen width).
local opts = { file = "", w = 0, h = 0, width = 0.175 }
require("mp.options").read_options(opts, "tv7idle")

local shown = nil   -- position/size of the overlay on screen, nil = not shown

local function update()
    local dim = mp.get_property_native("osd-dimensions")
    local want = nil
    if mp.get_property_bool("idle-active") and opts.file ~= "" and opts.w > 0 and opts.h > 0 and dim and dim.w > 0 and dim.h > 0 then
        local dw = math.floor(dim.w * opts.width + 0.5)
        local dh = math.floor(dw * opts.h / opts.w + 0.5)
        want = string.format("%d %d %d %d", math.floor((dim.w - dw) / 2), math.floor((dim.h - dh) / 2), dw, dh)
    end
    if want == shown then
        return
    end
    if want then
        local x, y, dw, dh = want:match("(%d+) (%d+) (%d+) (%d+)")
        mp.commandv("overlay-add", 0, x, y, opts.file, 0, "bgra", opts.w, opts.h, opts.w * 4, dw, dh)
    else
        mp.commandv("overlay-remove", 0)
    end
    shown = want
end

mp.observe_property("idle-active", "bool", update)
mp.observe_property("osd-dimensions", "native", update)
