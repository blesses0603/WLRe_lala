// Place in a private Unity 2021.3 project's Assets/Editor directory.
// Exports the currently loaded scene's physics geometry, never modifies game data.
using UnityEngine;
using UnityEditor;
using UnityEngine.SceneManagement;
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using System.Security.Cryptography;
using System.Threading.Tasks;

public class LaLaCollisionExport : EditorWindow {
    int layerMask = 0;
    bool colliders = true, terrains = true;
    string modelId = "", graphSettingsSha256 = "", sceneBundleSha256 = "", dependencySha256 = "";
    [Serializable] class Source {
        public string model_id, graph_settings_sha256, scene_bundle_sha256, dependency_bundle_sha256;
        public int layer_mask, collider_count, terrain_count;
        public bool dynamic_obstacles_verified = false;
    }
    [MenuItem("LaLa/Export loaded scene collision geometry")]
    static void Open() { GetWindow<LaLaCollisionExport>("LaLa collision export"); }
    void OnGUI() {
        EditorGUILayout.HelpBox("Use a private copy of the 1275 scene. Match the official Recast layer mask and rasterize flags. This exports offline candidates only.", MessageType.Info);
        modelId = EditorGUILayout.TextField("Model ID", modelId);
        graphSettingsSha256 = EditorGUILayout.TextField("Graph settings SHA256", graphSettingsSha256);
        sceneBundleSha256 = EditorGUILayout.TextField("Scene Bundle SHA256", sceneBundleSha256);
        dependencySha256 = EditorGUILayout.TextField("Dependency SHA256", dependencySha256);
        layerMask = EditorGUILayout.IntField("Official layer bitmask", layerMask);
        colliders = EditorGUILayout.Toggle("Rasterize colliders", colliders);
        terrains = EditorGUILayout.Toggle("Rasterize terrain", terrains);
        if (GUILayout.Button("Load verified scene pair (Play Mode)")) LoadPair();
        if (GUILayout.Button("Export geometry")) {
            try { Export(); } catch (Exception e) { Debug.LogException(e); EditorUtility.DisplayDialog("Export rejected",e.Message,"OK"); }
        }
    }
    static readonly List<AssetBundle> loaded = new List<AssetBundle>();
    static string FileSha(string path) {
        using(var stream=File.OpenRead(path)) using(var hash=SHA256.Create())
            return BitConverter.ToString(hash.ComputeHash(stream)).Replace("-","").ToLowerInvariant();
    }
    async void LoadPair() {
        try {
            if(!EditorApplication.isPlaying) throw new Exception("Enter Play Mode in the private empty project first.");
            if(loaded.Count!=0) throw new Exception("Leave and re-enter Play Mode before loading another pair.");
            if(!Sha(sceneBundleSha256)||!Sha(dependencySha256)) throw new Exception("Supply verified source SHA256 values first.");
            string dep=EditorUtility.OpenFilePanel("Choose private dependency Bundle or __data","","");
            if(dep=="")return;
            string scene=EditorUtility.OpenFilePanel("Choose private scene Bundle or __data","","");
            if(scene=="")return;
            if(FileSha(dep)!=dependencySha256||FileSha(scene)!=sceneBundleSha256) throw new Exception("Scene/dependency SHA256 mismatch");
            AssetBundle d=AssetBundle.LoadFromFile(dep);
            if(d==null)throw new Exception("Dependency Bundle could not load");loaded.Add(d);
            AssetBundle b=AssetBundle.LoadFromFile(scene);
            if(b==null)throw new Exception("Scene Bundle could not load");loaded.Add(b);
            string[] paths=b.GetAllScenePaths();
            if(paths.Length!=1)throw new Exception("Expected exactly one scene in the selected bundle");
            AsyncOperation operation=SceneManager.LoadSceneAsync(paths[0],LoadSceneMode.Additive);
            if(operation==null)throw new Exception("Unity refused to load this scene");
            while(!operation.isDone)await Task.Yield();
            if(!EditorApplication.isPlaying)throw new Exception("Play Mode ended before loading completed");
            if(!SceneManager.SetActiveScene(SceneManager.GetSceneByPath(paths[0])))throw new Exception("Could not select loaded scene");
        } catch(Exception e) {Debug.LogException(e);EditorUtility.DisplayDialog("Load rejected",e.Message,"OK");}
    }
    static bool Sha(string value) { return System.Text.RegularExpressions.Regex.IsMatch(value,"^[0-9a-f]{64}$"); }
    static bool Included(GameObject o,int mask) { return o.scene == SceneManager.GetActiveScene() && o.scene.IsValid() && o.scene.isLoaded && o.activeInHierarchy && ((mask & (1 << o.layer)) != 0); }
    readonly List<Vector3> vertices = new List<Vector3>();
    readonly List<int> triangles = new List<int>();
    void Add(Vector3[] points,int[] indices,Matrix4x4 matrix) {
        if (vertices.Count+points.Length>2000000 || triangles.Count+indices.Length>12000000) throw new Exception("Geometry budget exceeded; split and verify scan tiles.");
        int start=vertices.Count;
        foreach(Vector3 v in points) {
            Vector3 p=matrix.MultiplyPoint3x4(v);
            if (float.IsNaN(p.x)||float.IsNaN(p.y)||float.IsNaN(p.z)||float.IsInfinity(p.x)||float.IsInfinity(p.y)||float.IsInfinity(p.z)) throw new Exception("Non-finite transformed vertex");
            vertices.Add(p);
        }
        if (indices.Length%3!=0) throw new Exception("Non-triangle geometry");
        bool reflected=matrix.determinant<0;
        for(int i=0;i<indices.Length;i+=3) {
            int a=indices[i],b=indices[i+1],c=indices[i+2];
            if(a<0||b<0||c<0||a>=points.Length||b>=points.Length||c>=points.Length) throw new Exception("Mesh index outside vertex buffer");
            triangles.Add(start+a);triangles.Add(start+(reflected?c:b));triangles.Add(start+(reflected?b:c));
        }
    }
    void Export() {
        int id;
        if(!int.TryParse(modelId,out id)||id<=0||!Sha(graphSettingsSha256)||!Sha(sceneBundleSha256)||!Sha(dependencySha256)) throw new Exception("Supply verified model and source SHA256 values first.");
        if(layerMask==0) throw new Exception("An explicit nonempty official rasterizer layer mask is required.");
        vertices.Clear();triangles.Clear();int nc=0,nt=0;
        if(colliders) foreach(Collider c in Resources.FindObjectsOfTypeAll<Collider>()) {
            if(!Included(c.gameObject,layerMask)||!c.enabled||c.isTrigger) continue;
            if(c is TerrainCollider) continue; // Controlled by rasterizeTerrain, never sneak in through colliders.
            MeshCollider mc=c as MeshCollider;
            BoxCollider box=c as BoxCollider;
            if(mc!=null) {
                if(mc.convex) throw new Exception("Convex collision hull requires a verified hull extractor: "+mc.name);
                if(mc.sharedMesh==null) throw new Exception("Missing collider Mesh: "+mc.name);
                Mesh m=mc.sharedMesh;
                for(int sub=0;sub<m.subMeshCount;sub++) if(m.GetTopology(sub)!=MeshTopology.Triangles) throw new Exception("Unsupported collider topology");
                Add(m.vertices,m.triangles,c.transform.localToWorldMatrix);
            } else if(box!=null) {
                Vector3 e=box.size*.5f,o=box.center;
                Vector3[] p={o+new Vector3(-e.x,-e.y,-e.z),o+new Vector3(e.x,-e.y,-e.z),o+new Vector3(e.x,-e.y,e.z),o+new Vector3(-e.x,-e.y,e.z),o+new Vector3(-e.x,e.y,-e.z),o+new Vector3(e.x,e.y,-e.z),o+new Vector3(e.x,e.y,e.z),o+new Vector3(-e.x,e.y,e.z)};
                int[] t={0,1,2,0,2,3,4,6,5,4,7,6,0,4,5,0,5,1,1,5,6,1,6,2,2,6,7,2,7,3,3,7,4,3,4,0};
                Add(p,t,c.transform.localToWorldMatrix);
            } else throw new Exception("Unsupported collider must not be silently omitted: "+c.GetType().Name+" / "+c.name);
            nc++;
        }
        if(terrains) foreach(Terrain t in Resources.FindObjectsOfTypeAll<Terrain>()) {
            if(!Included(t.gameObject,layerMask)||!t.enabled) continue;
            if(Quaternion.Angle(t.transform.rotation,Quaternion.identity)>.001f || (t.transform.lossyScale-Vector3.one).sqrMagnitude>.000001f) throw new Exception("Rotated/scaled Terrain requires source verification.");
            TerrainData d=t.terrainData;if(d==null) throw new Exception("TerrainData is missing");
            int r=d.heightmapResolution;
            if(d.holesResolution!=r-1) throw new Exception("Unknown Terrain hole grid layout");
            if((long)r*r>2000000-vertices.Count) throw new Exception("Terrain exceeds geometry budget");
            float[,] h=d.GetHeights(0,0,r,r);bool[,] surface=d.GetHoles(0,0,r-1,r-1);
            Vector3[] p=new Vector3[r*r];List<int> tri=new List<int>();
            for(int z=0;z<r;z++) for(int x=0;x<r;x++) p[z*r+x]=new Vector3(x*d.size.x/(r-1),h[z,x]*d.size.y,z*d.size.z/(r-1));
            for(int z=0;z<r-1;z++) for(int x=0;x<r-1;x++) if(surface[z,x]) {
                int a=z*r+x;tri.Add(a);tri.Add(a+r);tri.Add(a+1);tri.Add(a+1);tri.Add(a+r);tri.Add(a+r+1);
            }
            Add(p,tri.ToArray(),t.transform.localToWorldMatrix);nt++;
        }
        if(triangles.Count==0) throw new Exception("No supported collision/terrain triangles matched the official filters");
        string path=EditorUtility.SaveFilePanel("Private 1275 geometry","","1275_"+modelId+"_geometry.json","json");
        if(path=="") return;
        Source source=new Source{model_id=modelId,graph_settings_sha256=graphSettingsSha256,scene_bundle_sha256=sceneBundleSha256,dependency_bundle_sha256=dependencySha256,layer_mask=layerMask,collider_count=nc,terrain_count=nt};
        using(StreamWriter f=new StreamWriter(new FileStream(path,FileMode.CreateNew,FileAccess.Write))) {
            f.Write("{\"coordinate_space\":\"unity_world_y_up\",\"source\":"+JsonUtility.ToJson(source)+",\"vertices\":[");
            for(int i=0;i<vertices.Count;i++) {if(i>0)f.Write(',');Vector3 v=vertices[i];f.Write("["+v.x.ToString("R",CultureInfo.InvariantCulture)+","+v.y.ToString("R",CultureInfo.InvariantCulture)+","+v.z.ToString("R",CultureInfo.InvariantCulture)+"]");}
            f.Write("],\"triangles\":[");
            for(int i=0;i<triangles.Count;i+=3) {if(i>0)f.Write(',');f.Write("["+triangles[i]+","+triangles[i+1]+","+triangles[i+2]+"]");}
            f.Write("]}");
        }
        Debug.Log("Exported offline candidate geometry: "+path);
    }
}
