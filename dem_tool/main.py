import argparse
import json
import sys
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description='DEM Workflows: escritorio y ejecución reproducible por CLI')
    sub=parser.add_subparsers(dest='command')
    gui=sub.add_parser('gui'); gui.add_argument('--project')
    run=sub.add_parser('run'); run.add_argument('workflow'); run.add_argument('--dem',required=True); run.add_argument('--mask'); run.add_argument('--point'); run.add_argument('--output',required=True); run.add_argument('--vertical-unit',choices=['m','ft','us-ft'],default='m')
    batch=sub.add_parser('batch'); batch.add_argument('workflow'); batch.add_argument('--csv',required=True); batch.add_argument('--output',required=True); batch.add_argument('--workers',type=int,default=1); batch.add_argument('--vertical-unit',choices=['m','ft','us-ft'],default='m')
    sub.add_parser('algorithms')
    args=parser.parse_args()
    from dem_tool.core.models import Project,Workflow
    if args.command in (None,'gui'):
        from PySide6.QtWidgets import QApplication
        from dem_tool.gui.main_window import MainWindow
        app=QApplication(sys.argv); app.setApplicationName('DEM Workflows')
        window=MainWindow(Project.load(args.project) if getattr(args,'project',None) else None); window.show(); return app.exec()
    if args.command=='algorithms':
        from dem_tool.algorithms import load_algorithms
        print(json.dumps({k:{'title':a.title,'ports':a.ports,'parameters':a.defaults,'engine':a.engine} for k,a in load_algorithms().items()},indent=2,ensure_ascii=False)); return 0
    workflow=Workflow.load(args.workflow)
    if args.command=='run':
        from dem_tool.core.pipeline import Pipeline
        sources={'$dem':str(Path(args.dem).resolve())}
        for key in ('mask','point'):
            if getattr(args,key):sources['$'+key]=str(Path(getattr(args,key)).resolve())
        project=Project(Path(args.output),workflow,sources,vertical_unit=args.vertical_unit); project.save()
        report=Pipeline(project,on_event=lambda n,s,m:print(f'{n}: {s} {m}',flush=True)).run()
        project.layers=list(report.results.values()); project.save()
        print(json.dumps({'errors':report.errors,'exports':report.exports,'cache_hits':report.cache_hits,'log':report.log},indent=2))
        return 1 if report.errors else 0
    from dem_tool.batch.batch_processor import BatchProcessor,import_csv
    results=BatchProcessor(workflow,args.output,args.workers,vertical_unit=args.vertical_unit).run(import_csv(args.csv))
    print(json.dumps(results,indent=2,ensure_ascii=False)); return 1 if any(r['status']=='Error' for r in results.values()) else 0


if __name__=='__main__':sys.exit(main())
