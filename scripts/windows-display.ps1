# Dot-sourced in the test VM's console session by scripts/test-windows-vm.sh. Set-Display W H puts the
# screen at W x H for this session, and Reset-Display puts back the mode Windows has saved: the VM can
# be shared with other projects (coworker/vm), so the change isn't saved. Each returns ChangeDisplaySettings'
# result, 0 when it worked. Move-PointerAway puts the mouse pointer on the taskbar, off the window:
# a mode change centres it, over the tour's window, where it hovers a row.
Add-Type @"
using System; using System.Runtime.InteropServices;
public class AppKataDisplay {
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
  public struct DEVMODE {
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmDeviceName;
    public short dmSpecVersion, dmDriverVersion, dmSize, dmDriverExtra; public int dmFields;
    public int dmPositionX, dmPositionY, dmDisplayOrientation, dmDisplayFixedOutput;
    public short dmColor, dmDuplex, dmYResolution, dmTTOption, dmCollate;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmFormName;
    public short dmLogPixels; public int dmBitsPerPel, dmPelsWidth, dmPelsHeight, dmDisplayFlags, dmDisplayFrequency;
    public int dmICMMethod, dmICMIntent, dmMediaType, dmDitherType, dmReserved1, dmReserved2, dmPanningWidth, dmPanningHeight;
  }
  [DllImport("user32.dll")] public static extern int EnumDisplaySettings(string dev, int mode, ref DEVMODE dm);
  [DllImport("user32.dll")] public static extern int ChangeDisplaySettings(ref DEVMODE dm, int flags);
  [DllImport("user32.dll", EntryPoint = "ChangeDisplaySettings")] public static extern int Reset(IntPtr dm, int flags);
}
"@
function Set-Display([int]$Width, [int]$Height) {
    $dm = New-Object AppKataDisplay+DEVMODE
    $dm.dmSize = [Runtime.InteropServices.Marshal]::SizeOf($dm)
    [void][AppKataDisplay]::EnumDisplaySettings($null, -1, [ref]$dm)      # the current mode
    $dm.dmPelsWidth = $Width; $dm.dmPelsHeight = $Height; $dm.dmFields = 0x80000 -bor 0x100000
    [AppKataDisplay]::ChangeDisplaySettings([ref]$dm, 0)                  # 0: for now, not saved
}
function Reset-Display { [AppKataDisplay]::Reset([IntPtr]::Zero, 0) }
function Move-PointerAway {
    Add-Type -AssemblyName System.Windows.Forms, System.Drawing
    $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point([int]($b.Width * 0.6), ($b.Height - 4))
}
