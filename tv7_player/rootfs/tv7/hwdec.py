"""Hardware decoding per device: which decoder mpv uses, and whether its frames can be deinterlaced."""

import re


def deinterlace_possible(hwdec):
    """Software frames (no, *-copy) and VAAPI frames (mpv deinterlaces them with vavpp) can be deinterlaced. Frames that
    go straight to a display plane (drm on the Raspberry Pi) cannot: a deinterlace filter would turn hardware decoding
    off."""
    hwdec = hwdec or "no"
    return hwdec == "no" or hwdec.endswith("-copy") or hwdec.startswith("vaapi")


def pick_hwdec(vo, hwdec_help, v4l2_names, arch, render_node):
    """mpv arguments for the video output and the hardware decoding of this device. Returns (arguments, H.265 in
    hardware, log text).
    - Raspberry Pi 5 and 4, H.265: rpi-hevc-dec (V4L2 stateless, --hwdec=drm). These frames go straight to the display's
      bottom ("primary") plane; the GPU draws everything else (software-decoded channels, menu, technical info, idle
      logo) on the overlay plane above, which fix_planes makes opaque before mpv starts. Measured on the Pi 5: about
      0.15 of 4 cores instead of 3.
    - Raspberry Pi 4, H.264: bcm2835-codec (V4L2 stateful, --hwdec=v4l2m2m-copy); "copy" hands the frames back to normal
      memory, so software deinterlacing keeps working. Not tested on a Pi 4.
    - x86 with Intel or AMD graphics: VAAPI for H.264 and H.265, deinterlaced in hardware (vavpp); without the GPU
      output the frames are copied (vaapi-copy). Not tested on a device."""

    def has(name):
        return re.search(rf"^ *{re.escape(name)}( |$)", hwdec_help or "", re.M) is not None

    hevc = "rpi-hevc-dec" in (v4l2_names or "") and has("drm")
    h264 = "bcm2835-codec-decode" in (v4l2_names or "") and has("v4l2m2m-copy")
    vaapi = arch == "x86_64" and bool(render_node) and has("vaapi")
    args = ["--vo=gpu", "--gpu-context=drm"] if vo == "gpu" else ["--vo=drm"]
    if vaapi:
        return (
            args + ["--hwdec=vaapi" if vo == "gpu" else "--hwdec=vaapi-copy"],
            False,
            f"VAAPI ({render_node}), all codecs the GPU supports",
        )
    hw, codecs, msg = [], [], []
    if hevc and vo == "gpu":
        args += [
            "--gpu-hwdec-interop=drmprime-overlay",
            "--drm-draw-plane=overlay",
            "--drm-drmprime-video-plane=primary",
        ]
        hw, codecs, msg = ["drm"], ["hevc"], ["H.265 on the Raspberry Pi HEVC decoder"]
    if h264:
        hw, codecs, msg = (
            hw + ["v4l2m2m-copy"],
            codecs + ["h264"],
            msg + ["H.264 on the Raspberry Pi 4 decoder (v4l2m2m-copy, not tested)"],
        )
    if hw:
        return (
            args + [f"--hwdec={','.join(hw)}", f"--hwdec-codecs={','.join(codecs)}"],
            "drm" in hw,
            "; ".join(msg) + "; other channels in software",
        )
    return (
        args + ["--hwdec=auto-safe"],
        False,
        f"mpv auto-safe (Raspberry Pi HEVC decoder: {'yes' if hevc else 'no'}, video output {vo})",
    )
