// Offline Recast 1.6.0 adapter. Reads world-space triangles, writes scan results.
#include "Recast.h"
#include <cmath>
#include <iostream>
#include <iomanip>
#include <memory>
#include <stdexcept>
#include <vector>

template<class T, void(*Release)(T*)> using RcPtr=std::unique_ptr<T,decltype(Release)>;
static void require(bool ok,const char* message) { if(!ok) throw std::runtime_error(message); }
int main() {
 try {
    int nv,nt; rcConfig cfg{};
    float height,climb,radius,minArea,mergeArea;
    require(bool(std::cin>>nv>>nt>>cfg.cs>>cfg.ch>>height>>climb>>radius
        >>cfg.walkableSlopeAngle>>cfg.maxEdgeLen>>cfg.maxSimplificationError
        >>minArea>>mergeArea>>cfg.detailSampleDist>>cfg.detailSampleMaxError),"Invalid scan header");
    require(nv>=3 && nv<=2000000 && nt>0 && nt<=4000000,"Geometry count out of bounds");
    require(cfg.cs>0 && cfg.ch>0 && height>0 && climb>=0 && radius>=0
        && cfg.walkableSlopeAngle>=0 && cfg.walkableSlopeAngle<90,"Invalid agent settings");
    std::vector<float> verts(nv*3);std::vector<int> tris(nt*3);
    for(float& v:verts) require(bool(std::cin>>v) && std::isfinite(v),"Invalid vertex");
    for(int& t:tris) require(bool(std::cin>>t) && t>=0 && t<nv,"Invalid triangle index");
    for(float& v:cfg.bmin)require(bool(std::cin>>v) && std::isfinite(v),"Invalid minimum bounds");
    for(float& v:cfg.bmax)require(bool(std::cin>>v) && std::isfinite(v),"Invalid maximum bounds");
    for(int a=0;a<3;++a)require(cfg.bmax[a]>cfg.bmin[a],"Empty scan bounds");
    require(std::isfinite(minArea) && std::isfinite(mergeArea) && minArea>=0 && mergeArea>=0
        && minArea<=16000000 && mergeArea<=16000000 && cfg.maxEdgeLen>=0
        && cfg.maxSimplificationError>=0 && std::isfinite(cfg.maxSimplificationError)
        && cfg.detailSampleDist>=0 && std::isfinite(cfg.detailSampleDist)
        && cfg.detailSampleMaxError>=0 && std::isfinite(cfg.detailSampleMaxError)
        && radius/cfg.cs<=32768 && climb/cfg.ch<=8191,"Recast parameter limits exceeded");
    cfg.walkableHeight=int(std::ceil(height/cfg.ch));
    cfg.walkableClimb=int(std::floor(climb/cfg.ch));
    cfg.walkableRadius=int(std::ceil(radius/cfg.cs));
    cfg.minRegionArea=int(minArea);cfg.mergeRegionArea=int(mergeArea);
    cfg.maxVertsPerPoly=6;
    require(cfg.walkableHeight>=3 && cfg.walkableHeight<RC_SPAN_MAX_HEIGHT,"Agent height outside Recast span range");
    require((cfg.bmax[1]-cfg.bmin[1])/cfg.ch<RC_SPAN_MAX_HEIGHT,"Vertical voxel range overflow");
    require(double(cfg.bmax[0]-cfg.bmin[0])/cfg.cs<=32768
         && double(cfg.bmax[2]-cfg.bmin[2])/cfg.cs<=32768,"Grid dimensions too large");
    rcCalcGridSize(cfg.bmin,cfg.bmax,cfg.cs,&cfg.width,&cfg.height);
    require(cfg.width>0 && cfg.height>0 && double(cfg.width)*cfg.height<=16000000,"Grid cell budget exceeded; split into verified tiles");
    rcContext context;
    RcPtr<rcHeightfield,rcFreeHeightField> solid(rcAllocHeightfield(),rcFreeHeightField);
    RcPtr<rcCompactHeightfield,rcFreeCompactHeightfield> compact(rcAllocCompactHeightfield(),rcFreeCompactHeightfield);
    RcPtr<rcContourSet,rcFreeContourSet> contours(rcAllocContourSet(),rcFreeContourSet);
    RcPtr<rcPolyMesh,rcFreePolyMesh> poly(rcAllocPolyMesh(),rcFreePolyMesh);
    RcPtr<rcPolyMeshDetail,rcFreePolyMeshDetail> detail(rcAllocPolyMeshDetail(),rcFreePolyMeshDetail);
    require(solid && compact && contours && poly && detail,"Recast allocation failed");
    require(rcCreateHeightfield(&context,*solid,cfg.width,cfg.height,cfg.bmin,cfg.bmax,cfg.cs,cfg.ch),"Heightfield failed");
    std::vector<unsigned char> areas(nt,RC_NULL_AREA);
    rcMarkWalkableTriangles(&context,cfg.walkableSlopeAngle,verts.data(),nv,tris.data(),nt,areas.data());
    require(rcRasterizeTriangles(&context,verts.data(),nv,tris.data(),areas.data(),nt,*solid,cfg.walkableClimb),"Rasterization failed");
    rcFilterLowHangingWalkableObstacles(&context,cfg.walkableClimb,*solid);
    rcFilterLedgeSpans(&context,cfg.walkableHeight,cfg.walkableClimb,*solid);
    rcFilterWalkableLowHeightSpans(&context,cfg.walkableHeight,*solid);
    require(rcBuildCompactHeightfield(&context,cfg.walkableHeight,cfg.walkableClimb,*solid,*compact),"Compact heightfield failed");
    solid.reset();
    require(rcErodeWalkableArea(&context,cfg.walkableRadius,*compact),"Agent-radius erosion failed");
    require(rcBuildDistanceField(&context,*compact),"Distance field failed");
    require(rcBuildRegions(&context,*compact,0,cfg.minRegionArea,cfg.mergeRegionArea),"Regions failed");
    require(rcBuildContours(&context,*compact,cfg.maxSimplificationError,cfg.maxEdgeLen,*contours),"Contours failed");
    require(rcBuildPolyMesh(&context,*contours,cfg.maxVertsPerPoly,*poly),"Polygons failed");
    if(poly->npolys==0){std::cout<<"{\"vertices\":[],\"triangles\":[]}\n";return 0;}
    require(rcBuildPolyMeshDetail(&context,*poly,*compact,cfg.detailSampleDist,cfg.detailSampleMaxError,*detail),"Detail mesh failed");
    std::cout<<std::setprecision(9)<<"{\"vertices\":[";
    for(int v=0;v<detail->nverts;++v){if(v)std::cout<<',';std::cout<<'['<<detail->verts[v*3]<<','<<detail->verts[v*3+1]<<','<<detail->verts[v*3+2]<<']';}
    std::cout<<"],\"triangles\":[";bool first=true;
    for(int m=0;m<detail->nmeshes;++m){const unsigned int* mesh=&detail->meshes[m*4];
        for(unsigned int t=0;t<mesh[3];++t){if(!first)std::cout<<',';first=false;const unsigned char* tri=&detail->tris[(mesh[2]+t)*4];
            std::cout<<'['<<mesh[0]+tri[0]<<','<<mesh[0]+tri[1]<<','<<mesh[0]+tri[2]<<']';}}
    std::cout<<"]}\n";return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 2;}
}
