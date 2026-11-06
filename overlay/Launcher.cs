using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;
[assembly: AssemblyTitle("洛克PVP")]
[assembly: AssemblyProduct("洛克PVP 对战助手")]
[assembly: AssemblyDescription("迪莫 · 工作台与实战连接控制台")]
[assembly: AssemblyVersion("1.0.0.0")]

internal static class Launcher
{
    [STAThread]
    private static void Main(string[] args)
    {
        try
        {
            string root = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
            string electron = Path.Combine(root, "overlay", "node_modules", "electron", "dist", "electron.exe");
            if (!File.Exists(electron)) throw new FileNotFoundException("Electron runtime is missing. Keep this EXE in the project folder.", electron);
            ProcessStartInfo start = new ProcessStartInfo(electron);
            start.Arguments = "\"" + Path.Combine(root, "overlay") + "\" --no-sandbox --disable-gpu --disable-gpu-sandbox --in-process-gpu";
            if (Array.IndexOf(args, "--verify-desktop") >= 0) start.Arguments += " --verify-desktop";
            start.WorkingDirectory = root;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.WindowStyle = ProcessWindowStyle.Hidden;
            start.EnvironmentVariables.Remove("ELECTRON_RUN_AS_NODE");
            Process.Start(start);
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "Roco PVP - Startup error", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
